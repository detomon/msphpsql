#!/usr/bin/python3
"""
 Description: This script intended to run the Performance Tests on Windows, Linux and Mac. 
 Requirements: 
              Run setup_env_unix.sh( Linux and Mac ) or setup_env_windows.ps1( Windows ) before invoking  this script.
              modify lib/connect.php with the credentials to connect to the test database.
"""

import shutil
from shutil import copyfile
import os
import sys
import argparse
import subprocess
import fileinput
import subprocess
from subprocess import call
import xml.etree.ElementTree as ET
import pyodbc
import platform
import re
import datetime
import time
from time import strftime
import hashlib

"""
 Paths to current benchmarks. These constants should be modified if there are any changes in folder structure of the project.
"""

sqlsrv_path = "benchmark" + os.sep + "sqlsrv"
pdo_path = "benchmark" + os.sep + "pdo_sqlsrv"

"""
 Path to the connect.php file that contains test database credentials. Note that, the benchmarks are run against this database and it is different from Result database.
"""
connect_file = "lib" + os.sep + "connect.php"
connect_file_bak = connect_file + ".bak"
result_file = "lib" + os.sep + "result_db.php"

"""
 Global data format used across the script
"""
fmt = "%Y-%m-%d %H:%M:%S.0000000"

def validate_platform( platform_name ):
    """
    This module validates the platform name passed in to the script as an argument.
    If no match, the script will stop the execution.
    Args:
        platform_name (str): Platform name to validate 
    Returns:
        N/A
    """
    platforms = [
          "Windows10"
        , "WindowsServer2016"
        , "WindowsServer2012"
        , "Ubuntu16"
        , "RedHat7"
        , "SUSE12"
        , "Sierra"]
    if platform_name not in platforms:
        print ( "Platform must be one of the following:" )
        print( platforms )
        exit( 1 )
 
class DB( object ):
    """
    A class to keep database credentials
    Attributes:
        server_name (str): The name or the IP address of the server.
        database_name (str): The name of the database
        username (str): Database username
        password (str): Database password for username
    """
    def __init__ ( self
        , server_name = None
        , database_name = None
        , username = None
        , password = None):
            self.server_name = server_name
            self.database_name = database_name
            self.username = username
            self.password = password
 
class XMLResult( object ):
    """
    A class to keep a result set of a benchmark generated by PHPBench as an XML file.
    Attributes:
        benchmark_name (str): The name or the benchmark.
        success (int): 0 or 1. 0 if the benchmark failed to execute, 1 if the execution was successful.
        duration (int,optional): In case of success, time taken to run the benchmark. 
        memory (int, optional): In case of success, memory peak when executing the benchmark.
        iterations(int, optional): In case of success, number of iterations the benchmark was run for.
        error_message(str, optional): In case of failure, descriptive error message.   
    """
    def __init__ ( self
        , benchmark_name = None
        , success = None
        , duration = None
        , memory = None
        , iterations = None
        , error_message = None ):
            self.benchmark_name = benchmark_name
            self.success = success
            self.duration = duration
            self.memory = memory
            self.iterations = iterations
            self.error_message = error_message
 
def get_test_name( name ):
    """
    This module maps PHPBench benchmark names to the names that are used accross the teams.
    Args:
        name (str): Name of the benchmark
    Returns: 
        The mapped name
    Raises:
        KeyError when the name passed in does not match any of the keys
    """
    test_name_dict = {
          'SqlsrvConnectionBench': 'connection'
        , 'SqlsrvCreateDbTableProcBench': 'create'
        , 'SqlsrvCRUDBench': 'crud'
        , 'SqlsrvInsertBench': 'crud-create'    
        , 'SqlsrvFetchBench': 'crud-retrieve'  
        , 'SqlsrvUpdateBench': 'crud-update'    
        , 'SqlsrvDeleteBench': 'crud-delete'
        , 'SqlsrvFetchLargeBench': 'large'
        , 'SqlsrvSelectVersionBench': 'version'
        , 'PDOConnectionBench': 'connection'
        , 'PDOCreateDbTableProcBench': 'create'
        , 'PDOCRUDBench': 'crud'
        , 'PDOInsertBench': 'crud-create'    
        , 'PDOFetchBench': 'crud-retrieve'  
        , 'PDOUpdateBench': 'crud-update'    
        , 'PDODeleteBench': 'crud-delete'
        , 'PDOFetchLargeBench': 'large'
        , 'PDOSelectVersionBench': 'version'
    }
    return test_name_dict[ name ]
 
def get_run_command( path_to_tests, dump_file ):
    """
    This module returns the command to run the tests
    Args:
        path_to_tests (str): The folder that contains the tests to be run
        dump_file (str): The name of the XML file to output the results
    Returns:
        The command to run the tests
    """
    command = "vendor" + os.sep + "bin" + os.sep + "phpbench run {0} --dump-file={1}"
    return command.format( path_to_tests, dump_file )
 
def get_id( conn, id_field, table, name_field, value ):
    """
    This module returns id of an entry when value is a string
    Args:
        conn (obj): A connection to the result database
        id_field (str): The name of the id column
        table (str): The name of the table that contains the entry
        name_field (str): The name of the field to compare the value against
        value (str): The value that its id is requested
    Returns:
        id of the value if the value exists in the table, None otherwise
    """
    query = "SELECT {0} FROM {1} WHERE {2}='{3}'"
    cursor = conn.cursor()
    cursor.execute( query.format( id_field, table, name_field, value ))
    id = cursor.fetchone()
    cursor.close()
    if id is not None:
        return id[0]
    return id
 
def get_id_no_quote( conn, id_field, table, name_field, value ):
    """
    This module returns id of an entry when value is not a string. 
    @TODO This is a hack, could not get binary binding working with pyodbc.
    This module should be removed and get_id should use binding parameters.
    Args:
        conn (obj): A connection to the result database
        id_field (str): The name of the id column
        table (str): The name of the table that contains the entry
        name_field (str): The name of the field to compare the value against
        value (bin): The value that its id is requested
    Returns:
        id of the value if the value exists in the table, None otherwise
    """
    query = "SELECT {0} FROM {1} WHERE {2}={3}"
    cursor = conn.cursor()
    cursor.execute( query.format( id_field, table, name_field, value ))
    id = cursor.fetchone()
    cursor.close()
    if id is not None:
        return id[0]
    return id
 
def get_test_database( database_file ):
    """
    This module reads test database details from connect.php and stores them into an instance of DB class
    Returns:
        A DB object that contains database credentials
    """
    test_db = DB()
    for line in open( database_file ):
        if "server" in line:
            test_db.server_name = line.split("=")[1].strip()[1:-2]
        elif "database" in line:
            test_db.database_name = line.split("=")[1].strip()[1:-2]        
        elif "uid" in line:
            test_db.username = line.split("=")[1].strip()[1:-2]
        elif "pwd" in line:
            test_db.password = line.split("=")[1].strip()[1:-2]
    return test_db
 
def connect( db ):
    """
    This module creates a connection to the given database
    Args:
        db (obj): database object
    Returns:
        A connection object to the given database       
    """
    return pyodbc.connect(
          driver="{ODBC Driver 13 for SQL Server}"
        , host=db.server_name
        , database=db.database_name
        , user=db.username
        , password=db.password
        , autocommit = True)
 
def get_server_version( server ):
    """
    This module returns the version of the given server
    Args:
        server (obj): Server object to connect to
    Returns:
        The output of @@Version
    """
    conn = connect( server )
    cursor = conn.cursor()
    cursor.execute( "SELECT @@VERSION")
    version = cursor.fetchone()[0]
    cursor.close()
    return version
 
def get_sha1_file( filename ):
    """
    This module generates sha1sum for the given file
    Args:
        filename (str): Full path to the file
    Returns:
        sha1sum hash of the file
    """
    hash_size = 256
    sha1 = hashlib.sha256()
    with open( filename, 'rb' ) as f:
        while True:
            data = f.read( hash_size )
            if not data:
                break
            sha1.update( data )
    return "0x" + sha1.hexdigest()
       
def insert_server_entry( conn, server_name, server_version ):
    """
    This module inserts a new entry into Servers table
    Args:
        conn (obj): Connection object to the Results database
        server_name (str): Name of the Test Server that the tests are run against
        server_version (str): @@Version of the Test Server
    Returns:
        N/A
    """
    query = "INSERT INTO Servers ( HostName, Version ) VALUES ( '{0}', '{1}' )"
    cursor = conn.cursor()
    cursor.execute( query.format( server_name, server_version ))
    cursor.close()
 
def insert_client_entry ( conn, name ):
    """
    This module inserts a new entry into Clients table
    Args:
        conn (obj): Connection object to the Results database
        name (str): Name of the Client machine that the tests are run on
    Returns:
        N/A
    """
    query = "INSERT INTO Clients ( HostName ) VALUES( '{0}' )"
    cursor = conn.cursor()
    cursor.execute( query.format( name ))
    cursor.close()
 
def insert_team_entry ( conn, name ):
    """
    This module inserts a new entry into Teams table
    Args:
        conn (obj): Connection object to the Results database
        name (str): Team name
    Returns:
        N/A
    """
    query = "INSERT INTO Teams ( TeamName ) VALUES( '{0}' )"
    cursor = conn.cursor()
    cursor.execute( query.format( name ))
    cursor.close()
 
def insert_test_entry( conn, name ):
    """
    This module inserts a new entry into PerformanceTests table
    Args:
        conn (obj): Connection object to the Results database
        name (str): Test name
    Returns:
        N/A    
    """
    #TO-DO Remove unnecessary columns from the table and fix the query string. Amd64 and 0 are used to bypass not null
    query = "INSERT INTO PerformanceTests ( TestName, Arch, HashVer ) VALUES( '{0}', 'Amd64', 0 )"
    cursor = conn.cursor()
    cursor.execute( query.format( name ))
    cursor.close()
 
def insert_driver_entry( conn, driver_path, driver_hash ):
    """
    This module inserts a new entry into Drivers table
    Args:
        conn (obj): Connection object to the Results database
        name (str): Full path to the driver
        driver_hash (bin): sha1sum hash of the driver 
    Returns:
        N/A    
    """
    file_date = time.strftime( fmt, time.gmtime( os.path.getmtime( driver_path )))
    query = "INSERT INTO Drivers ( Arch, FileDate, SHA1, HashVer ) VALUES ( ?, ?, {0}, 1 )"
    cursor = conn.cursor()
    cursor.execute( query.format(driver_hash), ( get_php_arch(), file_date ))
    cursor.close()
 
def get_server_id( conn, test_db ):
    """
    This module retrieves the id of a Server entry. If the given server does not exist in Servers table, 
    the module inserts it into the Servers table and retrieves its id.
    Args:
        conn (obj): Connection object to the Results database
        test_db (obj): An object that contains Test Server details
    Returns:
        id of the given server  
    """
    server_id = get_id( conn, "ServerId", "Servers", "HostName", test_db.server_name )
    if server_id is None:
        insert_server_entry( conn, test_db.server_name, get_server_version( test_db ))
        server_id = get_id( conn, "ServerId", "Servers", "HostName", test_db.server_name )
    return server_id
 
def get_client_id( conn ):
    """
    This module retrieves the id of a Client entry. If the given client does not exist in Clients table, 
    the module inserts it into the Clients table and retrieves its id.
    Args:
        conn (obj): Connection object to the Results database
    Returns:
        id of the client
    """
    client_name = platform.node()
    client_id = get_id( conn, "ClientId", "Clients", "HostName", client_name )
    if client_id is None:
        insert_client_entry( conn, client_name )
        client_id = get_id( conn, "ClientId", "Clients", "HostName", client_name )
    return client_id
 
def get_team_id( conn ):
    """
    This module retrieves the id of a Team entry. If the given team name - PHP does not exist in Teams table, 
    the module inserts it into the Teams table and retrieves its id.
    Args:
        conn (obj): Connection object to the Results database
    Returns:
        id of the team
    """
    team_name = "PHP"
    team_id = get_id( conn, "TeamId", "Teams", "TeamName", team_name)
    if team_id is None:
        insert_team_entry( conn, team_name )
        team_id = get_id( conn, "TeamId", "Teams", "TeamName", team_name)
    return team_id
 
def get_test_id( conn, test_name ):
    """
    This module retrieves the id of a Test entry. If the given test does not exists in PerformanceTests table, 
    the module inserts it into the PerformanceTests table and retrieves its id.
    Args:
        conn (obj): Connection object to the Results database
        test_name (str): The name of the test that the id is requested for
    Returns:
        id of the test
    """
    test_id = get_id( conn, "TestId", "PerformanceTests", "TestName", test_name )
    if test_id is None:
        insert_test_entry( conn, test_name )
        test_id = get_id( conn, "TestId", "PerformanceTests", "TestName", test_name )
    return test_id
 
def get_driver_id( conn, driver_name ):
    """
    This module retrieves the id of a Driver entry. If the given driver does not exists in Drivers table, 
    the module inserts it into the Drivers table and retrieves its id.
    Args:
        conn (obj): Connection object to the Results database
        driver_name (str): The name of the driver that the id is requested for
    Returns:
        id of the driver
    """
    driver_path = get_path_to_driver( driver_name )
    driver_hash = get_sha1_file( driver_path )
    driver_id = get_id_no_quote( conn, "DriverId", "Drivers", "SHA1", driver_hash )
    if driver_id is None:
        insert_driver_entry( conn, driver_path, driver_hash )
        driver_id = get_id_no_quote( conn, "DriverId", "Drivers", "SHA1", driver_hash )
    return driver_id
       
def insert_result_entry_and_get_id( conn, test_id, client_id, driver_id, server_id, team_id, success ):
    """
    This module inserts a new result entry into PerformanceResults table and retrieves its id.
    Args:
        conn (obj): Connection object to the Results database
        test_id (int): The id of the test
        client_id (int): The id of the client that the test was run on
        driver_id (int): The id of the driver that the test was run against
        server_id (int): The id of the server that the test was run against
        team_id (int): The id of the team that the test belongs to
        success (int): 0 if the test failed, 1 otherwise
    Returns:
        id of the result
    """
    query = "INSERT INTO PerformanceResults( TestId, ClientId, DriverId, ServerId, TeamId, Success ) OUTPUT INSERTED.ResultId VALUES( {0}, {1}, {2}, {3}, {4}, {5} )"
    cursor = conn.cursor()
    cursor.execute( query.format( test_id, client_id, driver_id, server_id, team_id, success ))
    result_id = cursor.fetchone()
    cursor.close()
    if result_id is not None:
        return result_id[0]
    return id
 
def insert_result_key_value( conn, table_name, result_id, key, value ):
    """
    This module inserts a new entry into a key-value table. 
    Args:
        conn (obj): Connection object to the Results database
        table_name (string): The name of the table. Current possible values: KeyValueTableBigInt, KeyValueTableDate, KeyValueTableString
        result_id (int): The result id that is associated with the key-value table
        key (str): name of the property
        value (int, date, string): The value of the key
    Returns:
        N/A
    """
    query = "INSERT INTO {0} ( ResultId, name, value ) VALUES( ?, ?, ? )"
    cursor = conn.cursor()
    cursor.execute( query.format( table_name ), ( result_id, key, value ) )
    cursor.close()
 
def get_php_arch():
    """
    This module determines the architecture of the default php of the system
    Args:
        N/A
    Returns
        x86 or x64
    """
    p = subprocess.Popen( "php -r \"echo PHP_INT_SIZE;\"", stdout=subprocess.PIPE, shell = True )
    out, err = p.communicate()
    if out.decode('ascii') == "8":
        return "x64"
    elif out.decode('ascii') == "4":
        return "x86"
 
def get_php_version():
    """
    This module determines the version of the default php of the system
    Args:
        N/A
    Returns:
        php version
    """
    p = subprocess.Popen( "php -r \"echo phpversion();\"", stdout=subprocess.PIPE, shell = True )
    out, err = p.communicate()    
    return out.decode('ascii')
   
def get_php_thread():
    """
    This module determines the thread safety of the default php of the system
    Args:
        N/A
    Returns:
        nts or ts
    """
    if os.name == 'nt':
        command = "php -i | findstr \"Thread\""
    else:
        command = "php -i | grep 'Thread'"
    p = subprocess.Popen( command, stdout=subprocess.PIPE, shell = True )
    out, err = p.communicate()
    if out.decode('ascii').split()[3].strip() == 'disabled':
        return "nts"
    else:
        return "ts"    
 
def get_driver_version( driver_name ):
    """
    This module determines the version of the given php driver.
    Args:
        driver_name (str): Name of the driver. Possible values sqlsrv and pdo_sqlsrv
    Returns:
        The version of the given driver
    """
    command = "php -r \"echo phpversion('{0}');\""
    p = subprocess.Popen( command.format( driver_name ), stdout=subprocess.PIPE, shell = True )
    out, err = p.communicate()
    return out.decode('ascii')
 
def get_msodbcsql_version( test_db ):
    """
    This module determines the version of MSODBCSQL using the sqlsrv driver.
    Args:
        test_db (obj): An object that contains Test Server details
    Returns:
        MSODBCSQL version
    """
    command = "php -r \"echo sqlsrv_client_info( sqlsrv_connect( '{0}', array( 'UID'=>'{1}', 'PWD'=>'{2}')))['DriverVer'];\""
    p = subprocess.Popen( command.format( test_db.server_name, test_db.username, test_db.password ), stdout=subprocess.PIPE, shell = True )
    out, err = p.communicate()
    return out.decode('ascii')
 
def get_path_to_driver( driver_name ):
    """
    This module returns the full path to the given php driver
    Args:
        driver_name (str): Name of the driver. Possible values sqlsrv and pdo_sqlsrv   
    Returns:
        Full path to the given driver
    """
    p = subprocess.Popen( "php -r \"echo ini_get('extension_dir');\"", stdout=subprocess.PIPE, shell = True )
    out, err = p.communicate()
    extension_dir = out.decode('ascii')
    if os.name == 'nt':
        return extension_dir + os.sep + "php_" + driver_name + ".dll"
    else:
        return extension_dir + os.sep + driver_name + ".so"
 
def enable_mars():
    """
    This module enables MARS by modifying connect.php file
    """
    print( "Enabling MARS...")
    with fileinput.FileInput( connect_file, inplace=True, backup='.bak') as file:
        for line in file:
            print( line.replace( "$mars=false;", "$mars=true;" ), end='')      
 
def disable_mars():
    """
    This module disables MARS by modifying connect.php file
    """
    print( "Disabling MARS...")
    os.remove( connect_file )
    copyfile( connect_file_bak, connect_file )
 
def enable_pooling():
    """
    This module enables Connection Pooling. 
    On Windows, this is done by modifying connect.php file.
    On Linux and Mac, odbcinst.ini file needs to be modified.
    @TO-DO: Currently modifying odbcinst.ini requires root permissions.
    Copy the MSODBCSQL to a location which does not require sudo. 
    """
    print( "Enabling Pooling...")
    if os.name == 'nt':
        with fileinput.FileInput( connect_file, inplace=True, backup='.bak') as file:
            for line in file:
                print( line.replace( "$pooling=false;", "$pooling=true;" ), end='')
    else:
        # Get the location of odbcinst.ini
        odbcinst = os.popen( "odbcinst -j" ).read().splitlines()[1].split()[1]
        odbcinst_bak = odbcinst + ".bak"
 
        # Create a copy of odbcinst.ini
        copyfile( odbcinst, odbcinst_bak )
 
        # Lines to enable Connection pooling
        lines_to_append="CPTimeout=5\n[ODBC]\nPooling=Yes\n"
 
        with open( odbcinst, "a" ) as f:
            f.write( lines_to_append )
 
def disable_pooling():
    """
    This module disables Connection Pooling. 
    On Windows, this is done by modifying connect.php file.
    On Linux and Mac, odbcinst.ini file needs to be modified.
    @TO-DO: Currently modifying odbcinst.ini requires root permissions.
    Copy the MSODBCSQL to a location which does not require sudo. 
    """
    print("Disabling Pooling...")
    if os.name == 'nt':
        os.remove( connect_file )
        copyfile( connect_file_bak, connect_file )
    else:
        # Get the location of odbcinst.ini
        odbcinst = os.popen( "odbcinst -j" ).read().splitlines()[1].split()[1]
        odbcinst_bak = odbcinst + ".bak"
        os.remove( odbcinst )
        copyfile( odbcinst_bak, odbcinst )
        os.remove( odbcinst_bak )
 
def run_tests( php_driver, test_name ):
    """
    This module runs the tests using PHPBench
    Args:
        php_driver (str): Name of the driver to be tested: sqlsrv, pdo_sqlsrv, or both
        test_name (str): File name of the test or all
    Returns:
        N/A
    """
    print("Running the tests...")
    add_to_path = ''
    if test_name != 'all':
        add_to_path = os.sep + test_name
    if php_driver == 'sqlsrv' or php_driver == 'both':
            call( get_run_command( sqlsrv_path + add_to_path, "sqlsrv-results.xml" ), shell=True )
    if php_driver == 'pdo_sqlsrv' or php_driver == 'both':
            call( get_run_command( pdo_path + add_to_path, "pdo_sqlsrv-results.xml" ), shell=True )
 
def parse_results( dump_file ):
    """
    This module parses the .xml files generated by PHPBench
    @TO-DO: Currently only limited detailes are parsed, such as duration and peak memory.
    PHPBench reports a lot more information that can be helpful.
    Consider looking at the xml files.
    Args:
        dump_file (str): The name of the XML file to be parsed.
    Returns:
        An array of XMLResult objects, where each object contains benchmark information, such as duration and memory.
    """
    xml_results = []
    tree = ET.parse( dump_file )
    root = tree.getroot()
    # The following lines assume a certain xml structure. 
    # Get all the benchmarks in a list
    benchmarks = root[0].findall( 'benchmark' )
    for benchmark in benchmarks:
        xml_result = XMLResult()
        #Get the benchmark name and remove the leasing backslash
        xml_result.benchmark_name = benchmark.get( 'class' )[1:]
        errors = benchmark[0][0].find( 'errors' )
        # Store the error message and mark the benchmark as failed if something went wrong when running the benchmark.
        if( errors is not None ):
            xml_result.success = 0
            xml_result.error_message = errors[0].text
        # If the bechmark was run successfully, parse the results. This is where you would add code to parse more details about the benchmark.
        else:
            xml_result.success = 1
            # convert microseconds to seconds
            xml_result.duration = int( round( int( benchmark[0][0].find( 'stats' ).get( 'sum' )) / 1000000 ))
            iterations = benchmark[0][0].findall( 'iteration' )
            xml_result.iterations = len( iterations )
            # Memory peak is an iteration specific, so going through all the iterations and capturing the highest. 
            # Memory peak is usually the same for all iterations. 
            memory_peak = 0
            for iteration in iterations:
                iter_memory_peak = int( iteration.get( 'mem-peak' ))
                if iter_memory_peak > memory_peak:
                    memory_peak = iter_memory_peak
            xml_result.memory = memory_peak
        xml_results.append( xml_result )
    return xml_results
 
def parse_and_store_results( dump_file, test_db, result_db, platform, driver, start_time, mars, pooling ):
    """
    This module parses the given xml file and stores the results into Result Database.
    Args:
        dump_file (str): Name of the xml file that containst the results from PHPBench
        test_db (obj): An object that contains Test Database details
        result_db (obj): An object that contains Result Database details
        platform (str): The platform name that the tests are run on
        driver (str): Name of the driver, sqlsrv or pdo_sqlsrv
        start_time (date): Time when the script was run
        mars (int): 0 to turn MARS off, 1 otherwise
        pooling (int): 0 to turn Connection Pooling off, 1 otherwise
    Returns:
        N/A
    """
    # Check if the xml file actually exist
    if not os.path.exists(dump_file):
        print(dump_file + " does not exist")
        return
        
    # Connect to the Result Database
    conn = connect( result_db )
 
    server_id = get_server_id( conn, test_db )
    client_id = get_client_id( conn )
    team_id   = get_team_id( conn )
    driver_id = get_driver_id( conn, driver )
 
   
    php_arch    = get_php_arch()
    php_thread  = get_php_thread()
    php_version = get_php_version()
    driver_version = get_driver_version( driver )
    msodbcsql_version = get_msodbcsql_version( test_db )
 
    cursor  = conn.cursor()
    #parse the results from xml file
    results = parse_results( dump_file )
    # Store every result into the Result Database
    for result in results:
        test_name = get_test_name( result.benchmark_name )
        test_id   = get_test_id( conn, test_name )
        result_id = insert_result_entry_and_get_id( conn, test_id, client_id, driver_id, server_id, team_id, result.success )
 
        if result.success:
            insert_result_key_value( conn, "KeyValueTableBigInt", result_id, "duration",   result.duration )
            insert_result_key_value( conn, "KeyValueTableBigInt", result_id, "memory",     result.memory )
            insert_result_key_value( conn, "KeyValueTableBigInt", result_id, "iterations", result.iterations)
        else:
            insert_result_key_value( conn, "KeyValueTableString", result_id, "error", result.error_message )
 
        insert_result_key_value( conn, "KeyValueTableDate"  , result_id, "startTime"       , start_time )
        insert_result_key_value( conn, "KeyValueTableBigInt", result_id, "mars"            , mars )
        insert_result_key_value( conn, "KeyValueTableBigInt", result_id, "pooling"         , pooling )
        insert_result_key_value( conn, "KeyValueTableString", result_id, "driver"          , driver )
        insert_result_key_value( conn, "KeyValueTableString", result_id, "php_arch"        , php_arch )
        insert_result_key_value( conn, "KeyValueTableString", result_id, "os"              , platform )
        insert_result_key_value( conn, "KeyValueTableString", result_id, "php_thread"      , php_thread )
        insert_result_key_value( conn, "KeyValueTableString", result_id, "php_version"     , php_version )
        insert_result_key_value( conn, "KeyValueTableString", result_id, "msodbcsql"       , msodbcsql_version )
        insert_result_key_value( conn, "KeyValueTableString", result_id, "driver_version"  , driver_version )
 
def parse_and_store_results_all( test_db, result_db, platform, start_time, mars, pooling ):
    """
    This module parses the given sqlsrv-regular.xml, sqlsrv-large.xml,pdo_sqlsrv-regular.xml, pdo_sqlsrv-large.xml and stores the results into Result Database.
    Args:
        test_db (obj): An object that contains Test Database details
        result_db (obj): An object that contains Result Database details
        platform (str): The platform name that the tests are run on
        start_time (date): Time when the script was run
        mars (int): 0 to turn MARS off, 1 otherwise
        pooling (int): 0 to turn Connection Pooling off, 1 otherwise
    Returns:
        N/A
    
    """
    print("Parsing and storing the results...")
    parse_and_store_results( "sqlsrv-results.xml", test_db, result_db, platform, "sqlsrv", start_time, mars, pooling )
    parse_and_store_results( "pdo_sqlsrv-results.xml", test_db, result_db, platform, "pdo_sqlsrv", start_time, mars, pooling )
 
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument( '-platform',         '--PLATFORM',         required=True,  help='The name of the platform the tests run on' )
    parser.add_argument( '-php-driver',       '--PHP_DRIVER',       default='both', help='Name of the PHP driver: sqlsrv, pdo_sqlsrv or both')
    parser.add_argument( '-testname',        '--TESTNAME',        default='all',  help='File name for only one test or all' )
    args = parser.parse_args()
    
    # Start time is recorded only in the beginning of this script execution. So it is not benchmark specific.
    # Start time can be used to group the results
    start_time = datetime.datetime.now().strftime( fmt )
    print( "Start time: " + start_time )
 
    validate_platform( args.PLATFORM )
    result_db = get_test_database( result_file )
    test_db = get_test_database( connect_file )
 
    print("Running the tests with default settings...")
 
    run_tests( args.PHP_DRIVER, args.TESTNAME )
    parse_and_store_results_all( test_db, result_db, args.PLATFORM, start_time, 0, 0 )
    """
    The following lines are commented out, because it already takes a long time to run the tests with the default settings.
    Echo block can be uncommented and run separately. 
    
    print("Running the tests with MARS ON...")
    enable_mars()
    run_tests( args.PHP_DRIVER, args.TESTNAME )
    parse_and_store_results_all( test_db, result_db, args.PLATFORM, start_time, 1, 0 )
    disable_mars()
 
   
    print("Running the tests with Pooling ON...")
    enable_pooling()
    run_tests( args.PHP_DRIVER, args.TESTNAME )
    parse_and_store_results_all( test_db, result_db, args.PLATFORM, start_time, 0, 1 )
    disable_pooling()
    """
    exit()
 
  
