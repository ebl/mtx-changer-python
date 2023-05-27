#!/usr/bin/python3
#
# -----------------------------------------------------------------------------
# - 20230519 - mtx-changer-python.py v1.0 - Initial release
# -----------------------------------------------------------------------------
#
# - 20230519
# - Bill Arlofski - The purpose of this script will be to add more
#                   functionality than the original mtx-changer script had.
#                   This script is a rewrite of the mtx-changer bash/perl
#                   script in Python. A key additional feature this script
#                   will initially provide is the ability to automatically
#                   detect when a tape drive in a library is reporting that it
#                   needs to be cleaned, and then to load a cleaning tape from
#                   a slot to clean the drive, and return it back to its slot
#                   when the cleaning is complete.
#
# If you use this script every day and think it is worth anything, I am
# always grateful to receive donations of any size via:
#
# Venmo: @waa2k,
# or
# PayPal: @billarlofski
#
# The latest version of this script may be found at: https://github.com/waa
# ------------------------------------------------------------------------------
#
# BSD 2-Clause License
#
# Copyright (c) 2023, William A. Arlofski waa@revpol.com
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
# 1.  Redistributions of source code must retain the above copyright
# notice, this list of conditions and the following disclaimer.
#
# 2.  Redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS
# IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
# TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A
# PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED
# TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
# PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
# ----------------------------------------------------------------------------
#
# USER VARIABLES - All user variables should be configured in the config file.
# See the options -c and -s in the instructions. Because the defaults in this
# script may change and more variables may be added over time, it is highly
# recommended to make use of the config file for customizing the variable
# settings.
# ---------------------------------------------------------------------------
#
# Modified notes from the original bash/perl mtx-changer script
# -------------------------------------------------------------
# This script is called by the Bacula SD, configured in the Autochanger's ChangerCommand setting like:
#
# ChangerCommand = "/mnt/mtx/mtx-changer-python.py -c /mnt/mtx/mtx-changer-python.conf -s library_name %c %o %S %a %d %i %j"
#
# ./mtx-changer-python.py [-c <config>] [-s <section>] <chgr_device> <mtx_cmd> <slot> <drive_device> <drive_index> [<jobid>] [<jobname>]
#
# Options passed must be in the correct order and all <required> options must be passed to the script
# at start. Bacula's SD will always pass all options specified on the ChangerCommand line even though
# in some cases, not all of them are needed.

# In the example command line above, we can see that the '-c config' and '-s section' are optional but
# must come before the other <required> options. The jobid and jobname are also optional and if passed,
# they must be in the correct order.
#
#  By default, the Bacula SD will always call with all of the above arguments, even though
#  in come cases, not all are used.
#
#  Valid commands are:
#  - list      List available volumes in slot:volume format.
#  - listall   List all slots in one of the following formats:
#              - For Drives:         D:drive index:F:slot:volume - D:0:F:5:G03005TA or for an empty drive:               D:3:E
#              - For Slots:          S:slot:F:volume             - S:2:F:G03002TA   or for an empty slot:                S:1:E
#              - For Import/Export:  I:slot:F:volume             - I:41:F:G03029TA  or for am empty import/Export slot:  I:42:E
#  - loaded    Show which slot is loaded in a drive, else 0 if the drive is empty.
#  - unload    Unload a drive to a slot.
#  - load      Load a a slot to a drive.
#  - slots     Show the number of slots in the autochanger.
#  - transfer  Transfer a volume from one slot to another. In this case, the archive device is the destination slot.
#
#  Slots are numbered from 1.
#  Drives are numbered from 0.
# ----------------------------------------------------------------------------
#
# ============================================================
# Nothing below this line should need to be modified
# Set variables in /opt/bacula/scripts/mtx-changer-python.conf
# ============================================================
#
# Import the required modules
# ---------------------------
import os
import re
import sys
import random
import subprocess
from time import sleep
from docopt import docopt
from datetime import datetime
from configparser import ConfigParser, BasicInterpolation

# Set some variables
# ------------------
progname = 'MTX Changer - Python'
version = '1.00'
reldate = 'May 27, 2023'
progauthor = 'Bill Arlofski'
authoremail = 'waa@revpol.com'
scriptname = 'mtx-changer-python.py'
prog_info_txt = progname + ' - v' + version + ' - ' + scriptname \
                + '\nBy: ' + progauthor + ' ' + authoremail + ' (c) ' + reldate + '\n\n'

# This list is so that we can reliably convert the True/False strings
# from the config file into real booleans to be used in later tests.
# -------------------------------------------------------------------
cfg_file_true_false_lst = ['auto_clean', 'chk_drive', 'debug', 'include_import_export', 'inventory', 'offline', 'vxa_packetloader']

# Initialize these variables to satisfy the
# defaults in the do_load and do_unload functions.
# ------------------------------------------------
slot = drive_device = drv_idx = drive_index = ''

# List of tapeinfo codes indicating
# that a drive needs to be cleaned
# ---------------------------------
cln_codes = ['20', '21']

# Define the docopt string
# ------------------------
doc_opt_str = """
Usage:
    mtx-changer-python.py [-c <config>] [-s <section>] <chgr_device> <mtx_cmd> <slot> <drive_device> <drive_index> [<jobid>] [<jobname>]
    mtx-changer-python.py -h | --help
    mtx-changer-python.py -v | --version

Options:
-c, --config <config>     Configuration file. [default: /opt/bacula/scripts/mtx-changer-python.conf]
-s, --section <section>   Section in configuration file. [default: DEFAULT]

chgr_device               The library's /dev/sg#, or /dev/tape/by-id/*, or /dev/tape/by-path/* node.
mtx_cmd                   Valid commands are: slots, list, listall, loaded, load, unload, transfer.
slot                      The one-based library slot to load/unload, or the source slot for the transfer command.
drive_device              The drive's /dev/nst#, or /dev/tape/by-id/*-nst, or /dev/tape/by-path/* node.
                          Or, the destination slot for the transfer command.
drive_index               The zero-based drive index.
jobid                     Optional jobid. If present, it will be written after the timestamp to the log file.
jobname                   Optional job name. If present, it will be written after the timestamp to the log file.

-h, --help                Print this help message
-v, --version             Print the script name and version

"""

# Now for some functions
# ----------------------
def now():
    'Return the current date/time in human readable format.'
    return datetime.today().strftime('%Y-%m-%d %H:%M:%S')

def usage():
    'Show the instructions and script information.'
    print(doc_opt_str)
    print(prog_info_txt)
    sys.exit(1)

def log(text, level):
    'Given some text, write it to the mtx_log_file.'
    if debug:
        if level <= int(debug_level):
            with open(mtx_log_file, 'a+') as file:
                file.write(now() + ' - ' + ('JobId: ' + jobid + ' - ' if jobid not in ('', None) else '') \
                + ('Job: ' + jobname + ' - ' if jobname not in ('', None, '*System*') \
                else (jobname + ' - ' if jobname is not None else '')) \
                + (chgr_name + ' - ' if len(chgr_name) != 0 else '') + text + '\n')

def log_cmd_results(result):
    log('returncode: ' + str(result.returncode), 40)
    log('stdout:\n' + result.stdout, 40)
    log('stderr:\n' + result.stderr, 40)

def print_opt_errors(opt):
    'Print the incorrect variable and the reason it is incorrect.'
    if opt == 'config':
        error_txt = 'The config file \'' + config_file + '\' does not exist or is not readable.'
    elif opt == 'section':
        error_txt = 'The section [' + config_section + '] does not exist in the config file \'' + config_file + '\''
    elif opt == 'conf_version':
        error_txt = 'The config file conf_version variable (' + conf_version + ') does not match the script version (' + version + ')'
    elif opt == 'uname':
        error_txt = 'Could not determine the OS using the \'uname\' utility.'
    elif opt == 'command':
        error_txt = 'The command provided (' + mtx_cmd + ') is not a valid command.'
    return error_txt

def get_shell_result(cmd):
    'Given a command to run, return the subprocess.run result'
    log('In function: get_shell_result()', 50)
    result = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    return result

def get_ready_str():
    'Determine the OS so we can set the correct mt "ready" string.'
    log('In function: get_ready_str()', 50)
    cmd = 'uname'
    log('Getting OS so we can set the \'ready\' variable.', 20)
    log('shell command: ' + cmd, 30)
    result = get_shell_result(cmd)
    log_cmd_results(result)
    uname = result.stdout
    if uname == 'Linux\n':
        if os.path.isfile('/etc/debian_version'):
            cmd = 'mt --version|grep "mt-st"'
            log('shell command: ' + cmd, 30)
            result = get_shell_result(cmd)
            log_cmd_results(result)
            if result.returncode == 1:
                return 'drive status'
        else:
            cmd = 'mt --version|grep "GNU cpio"'
            log('shell command: ' + cmd, 30)
            result = get_shell_result(cmd)
            if debug:
                log_cmd_results(result)
            if result.returncode == 0:
                return 'drive status'
        return 'ONLINE'
    elif uname == 'SunOS\n':
        return 'No Additional Sense'
    elif uname == 'FreeBSD\n':
        return 'Current Driver State: at rest.'
    else:
        print('\n' + print_opt_errors('uname'))
        usage()

def do_loaded():
    'If the drive is loaded, return the slot that is in it, otherwise return 0'
    log('In function: do_loaded()', 50)
    log('Checking if drive device ' + drive_device + ' (drive index: ' + drive_index + ') is loaded.', 20)
    cmd = mtx_bin + ' -f ' + chgr_device + ' status'
    log('mtx command: ' + cmd, 30)
    result = get_shell_result(cmd)
    log_cmd_results(result)
    if result.returncode != 0:
        log('ERROR calling: ' + cmd, 20)
        # The SD will log this text in the error message after 'Result='
        # --------------------------------------------------------------
        print(result.stderr)
        sys.exit(result.returncode)
    # We re.search for drive_index:Full lines and then we return 0
    # if the drive is empty, or the number of the slot that is loaded
    # For the debug log, we also print the volume name and the slot.
    # TODO: Maybe skip the re.search and just get what I need with
    # the re.subs
    # ---------------------------------------------------------------
    drive_loaded_line = re.search('Data Transfer Element ' + drive_index + ':Full.*', result.stdout)
    if drive_loaded_line is not None:
        slot_and_vol_loaded = (re.sub('^Data Transfer Element.*Element (\d+) Loaded.*= (\w+)', '\\1 \\2', drive_loaded_line.group(0))).split()
        slot_loaded = slot_and_vol_loaded[0]
        vol_loaded = slot_and_vol_loaded[1]
        log('Drive index ' + drive_index + ' is loaded with volume ' + vol_loaded + ' from slot ' + slot_loaded + '.', 20)
        log('do_loaded output: ' + slot_loaded, 40)
        return slot_loaded
    else:
        log('Drive device ' + drive_device + ' (drive index: ' + drive_index + ') is empty.', 20)
        log('do_loaded output: 0', 40)
        return '0'

def do_slots():
    'Print the number of slots in the library.'
    log('In function: do_slots()', 50)
    log('Determining the number of slots in the library.', 20)
    cmd = mtx_bin + ' -f ' + chgr_device + ' status'
    log('mtx command: ' + cmd, 30)
    result = get_shell_result(cmd)
    log_cmd_results(result)
    if result.returncode != 0:
        log('ERROR calling: ' + cmd, 20)
        sys.exit(result.returncode)
    # Storage Changer /dev/tape/by-id/scsi-SSTK_L80_XYZZY_B:4 Drives, 44 Slots ( 4 Import/Export )
    # --------------------------------------------------------------------------------------------
    slots_line = re.search('Storage Changer.*', result.stdout)
    slots = re.sub('^Storage Changer.* Drives, (\d+) Slots.*', '\\1', slots_line.group(0))
    log('do_slots output: ' + slots, 40)
    return slots

def do_inventory():
    'Call mtx with the inventory command if the inventory variable is True.'
    log('In function: do_inventory()', 50)
    cmd = mtx_bin + ' -f ' + chgr_device + ' inventory'
    log('mtx command: ' + cmd, 30)
    result = get_shell_result(cmd)
    log_cmd_results(result)
    if result.returncode != 0:
        log('ERROR calling: ' + cmd, 20)
        sys.exit(result.returncode)
    return

def do_list():
    'Return the list of slots and volumes in the slot:volume format required by the SD.'
    log('In function: do_list()', 50)
    # Does this library require an inventory command before the list command?
    # -----------------------------------------------------------------------
    if inventory:
        do_inventory()
    cmd = mtx_bin + ' -f ' + chgr_device + ' status'
    log('mtx command: ' + cmd, 30)
    result = get_shell_result(cmd)
    log_cmd_results(result)
    if result.returncode != 0:
        log('ERROR calling: ' + cmd, 20)
        sys.exit(result.returncode)
    # Create lists of only FULL Data Transfer Elements, Storage Elements, and possibly
    # the Import/Export elements. Then concatenate them into one 'mtx_elements_list' list.
    # ------------------------------------------------------------------------------------
    mtx_elements_txt = ''
    data_transfer_elements_list = re.findall('Data Transfer Element \d+:Full.*\w', result.stdout)
    storage_elements_list = re.findall('Storage Element \d+:Full :.*\w', result.stdout)
    if include_import_export:
        importexport_elements_list = re.findall('Storage Element \d+ IMPORT.EXPORT:Full.*\w', result.stdout)
    mtx_elements_list = data_transfer_elements_list + storage_elements_list \
                      + (importexport_elements_list if 'importexport_elements_list' in locals() else [])
    # Parse the results of the list output and
    # format the way the SD expects to see it.
    # ----------------------------------------
    for element in mtx_elements_list:
        tmp_txt = re.sub('Data Transfer Element \d+:Full \(Storage Element (\d+) Loaded\)', '\\1', element)
        tmp_txt = re.sub('VolumeTag = ', '', tmp_txt)
        # waa - 20230518 - I need to find out what the actual packetloader text is so I can verify/test this.
        # Original grep/sed used in mtx-changer bash/perl script for VXA libraries:
        # grep " *Storage Element [1-9]*:.*Full" | sed "s/ *Storage Element //" | sed "s/Full :VolumeTag=//"
        # ---------------------------------------------------------------------------------------------------
        if vxa_packetloader:
            tmp_txt = re.sub(' *Storage Element [0-9]*:.*Full', '', tmp_txt)
            tmp_txt = re.sub('Full :VolumeTag=', '', tmp_txt)
        else:
            if include_import_export:
                tmp_txt = re.sub('Storage Element (\d+) IMPORT.EXPORT:Full :VolumeTag=(.*)', '\\1:\\2', tmp_txt)
            tmp_txt = re.sub('Storage Element ', '', tmp_txt)
            tmp_txt = re.sub('Full :VolumeTag=', '', tmp_txt)
            mtx_elements_txt += tmp_txt + ('' if element == mtx_elements_list[-1] else '\n')
    log('do_list output:\n' + mtx_elements_txt, 40)
    return mtx_elements_txt

def do_listall():
    'Return the list of slots and volumes in the format required by the SD.'
    log('In function: do_listall()', 50)
    # Does this library require an inventory command before the list command?
    # -----------------------------------------------------------------------
    if inventory:
        do_inventory()
    cmd = mtx_bin + ' -f ' + chgr_device + ' status'
    log('mtx command: ' + cmd, 30)
    result = get_shell_result(cmd)
    log_cmd_results(result)
    if result.returncode != 0:
        log('ERROR calling: ' + cmd, 20)
        sys.exit(result.returncode)
    # Create lists of ALL Data Transfer Elements, Storage Elements, and possibly Import/Export
    # elements - empty, or full. Then concatenate them into one 'mtx_elements_list' list.
    # ----------------------------------------------------------------------------------------
    mtx_elements_txt = ''
    data_transfer_elements_list = re.findall('Data Transfer Element \d+:.*\w', result.stdout)
    storage_elements_list = re.findall('Storage Element \d+:.*\w', result.stdout)
    if include_import_export:
        importexport_elements_list = re.findall('Storage Element \d+ IMPORT.EXPORT.*\w', result.stdout)
    mtx_elements_list = data_transfer_elements_list + storage_elements_list \
                      + (importexport_elements_list if 'importexport_elements_list' in locals() else [])
    # Parse the results of the list output and
    # format the way the SD expects to see it.
    # ----------------------------------------
    for element in mtx_elements_list:
        tmp_txt = re.sub('Data Transfer Element (\d+):Empty', 'D:\\1:E', element)
        tmp_txt = re.sub('Data Transfer Element (\d+):Full \(Storage Element (\d+) Loaded\):VolumeTag = (.*)', 'D:\\1:F:\\2:\\3', tmp_txt)
        tmp_txt = re.sub('Storage Element (\d+):Empty', 'S:\\1:E', tmp_txt)
        tmp_txt = re.sub('Storage Element (\d+):Full :VolumeTag=(.*)', 'S:\\1:F:\\2', tmp_txt)
        if include_import_export:
            tmp_txt = re.sub('Storage Element (\d+) IMPORT.EXPORT:Empty', 'I:\\1:E', tmp_txt)
            tmp_txt = re.sub('Storage Element (\d+) IMPORT.EXPORT:Full :VolumeTag=(.*)', 'I:\\1:F:\\2', tmp_txt)
        mtx_elements_txt += tmp_txt + ('' if element == mtx_elements_list[-1] else '\n')
    log('listall output:\n' + mtx_elements_txt, 40)
    return mtx_elements_txt

def do_getvolname():
    'Given a slot (or slot and device in the case of a transfer) return the volume name(s).'
    # If mtx_cmd is transfer we need to return src_vol and dst_vol
    # ------------------------------------------------------------
    log('In function: do_getvolname()', 50)
    global all_slots
    # Prevent calling listall() twice,
    # once for src_vol and once for dst_vol
    # -------------------------------------
    all_slots = do_listall()
    if mtx_cmd == 'transfer':
        vol = re.search('[SI]:' + slot + ':.:(.*)', all_slots)
        if vol:
            src_vol = vol.group(1)
        else:
            src_vol = ''
        vol = re.search('[SI]:' + drive_device + ':.:(.*)', all_slots)
        if vol:
            dst_vol = vol.group(1)
        else:
            dst_vol = ''
        return src_vol, dst_vol
    elif mtx_cmd == 'load':
        vol = re.search('[SI]:' + slot + ':.:(.*)', all_slots)
        if vol:
            return vol.group(1)
        else:
            # Slot we are loading might be in a drive
            # ---------------------------------------
            vol = re.search('D:' + drive_index + ':F:\d+:(.*)', all_slots)
            if vol:
                return vol.group(1)
            else:
                return ''
    elif mtx_cmd == 'unload':
        vol = re.search('D:' + drive_index + ':.:' + slot + ':(.*)', all_slots)
        if vol:
            return vol.group(1)
        else:
            return ''

def do_wait_for_drive():
    'Wait a maximum of load_wait seconds for the drive to become ready.'
    log('In function: do_wait_for_drive()', 50)
    s = 0
    while s <= int(load_wait):
        log('Waiting for drive to become ready.', 20)
        cmd = mt_bin + ' -f ' + drive_device + ' status'
        log('mt command: ' + cmd, 30)
        result = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        log_cmd_results(result)
        if re.search(ready, result.stdout):
            log('Device ' + drive_device + ' (drive index: ' + drive_index + ') reports ready.', 20)
            break
        log('Device ' + drive_device + ' (drive index: ' + drive_index + ') - not ready, sleeping for one second and retrying...', 20)
        sleep(1)
        s += 1
    if s == int(load_wait) + 1:
        log('The maximum \'load_wait\' time of ' + str(load_wait) + ' seconds has been reached.', 20)
        log('Timeout waiting for drive device ' + drive_device + ' (drive index: ' + drive_index + ')'
            + ' to signal that it is loaded. Perhaps the Device\'s "DriveIndex" is incorrect.', 20)
        log('Exiting with return code 1', 20)
        return 1
    else:
        log('Successfully loaded volume ' + ('(' + volume + ') ' if volume != '' else '') \
            + 'to drive device ' + drive_device + ' (drive index: ' + drive_index + ') from slot ' + slot + '.', 20)
        log('Exiting with return code 0', 20)
        return 0

def chk_for_cln_tapes():
    'Return a list of cleaning tapes in the library based on the cln_str variable.'
    # Return a list of slots containing cleaning tapes
    # ------------------------------------------------
    log('In function: chk_for_cln_tapes()', 50)
    cln_tapes = re.findall('D:\d+:F:(\d+):(' + cln_str + '.*)', all_slots)
    cln_tapes += re.findall('[SI]:(\d+):F:(' + cln_str + '.*)', all_slots)
    if len(cln_tapes) > 0:
        log('Found ' + ('the following cleaning tapes: ' + str(cln_tapes) if len(cln_tapes) != 0 else 'no cleaning tapes') + '.', 30)
    else:
        log('No cleaning tapes found in library.', 30)
        log('Skipping automatic cleaning.', 30)
    return cln_tapes

def do_clean(cln_tapes):
    'Given the cln_tapes list of available cleaning tapes, randomly pick one and load it.'
    log('In function: do_clean()', 50)
    log('Selecting a cleaning tape.', 30)
    cln_tuple = random.choice(cln_tapes)
    cln_slot = cln_tuple[0]
    cln_vol = cln_tuple[1]
    # If we chose a cleaning tape that is in a drive, we need to
    # unload it to its slot first, and then load into this drive.
    # -----------------------------------------------------------
    cln_tape_in_drv = re.search('^D:(\d+):F:' + cln_slot, all_slots)
    if cln_tape_in_drv:
        log('Whoops! Cleaning tape ' + cln_vol + ' is in a drive (drive index: ' + cln_tape_in_drv[1] + ') Unloading it...', 40)
        do_unload(cln_slot, '', cln_tape_in_drv[1], cln_vol, cln = True)
    log('Will load cleaning tape (' + cln_vol + ') from slot (' + cln_slot \
        + ') into drive device ' + drive_device + ' (drive index: ' + drive_index + ').', 20)
    do_load(cln_slot, drive_device, drive_index, cln_vol, cln = True)

def do_get_sg_node():
    'Given a drive_device, return the /dev/sg# node.'
    log('In function: do_get_sg_node()', 50)
    log('Determining the tape drive\'s /dev/sg# node.', 20)
    # First, we need to find the '/dev/sg#' node of the drive.
    # I do not want to trust what someone has put into the SD
    # Device's 'ControlDevice =', so I will use `lsscsi` to
    # identify the correct one.
    # --------------------------------------------------------
    # In Linux, a Device's 'ArchiveDevice = ' may be specified as '/dev/nst#' or
    # '/dev/tape/by-id/scsi-3XXXXXXXX-nst' (the preferred method), or even with
    # '/dev/tape/by-path/*', so I think we need to try to determine which one
    # it is and automatically figure out what field in the `lsscsi` output to
    # match it to. This can get even more fun™ when we think about the BSDs or
    # other OSes... So, work in progress here for sure.
    # --------------------------------------------------------------------------
    # drive_device = '/dev/nst0'
    # drive_device = '/dev/tape/by-id/scsi-350223344ab001200-nst'
    # drive_device = '/dev/tape/by-path/STK-T10000B-XYZZY_B1-nst'
    if '/dev/st' in drive_device or '/dev/nst' in drive_device:
        # OK, we caught the /dev/st# or /dev/nst# case
        # --------------------------------------------
        st = re.sub('/dev/n*(st\d+)', '\\1', drive_device)
    elif '/by-id' in drive_device:
        # OK, we caught the /dev/tape/by-id case
        # --------------------------------------
        st = re.sub('/dev/tape/by-id/scsi-3(.+?)-.*', '\\1', drive_device)
    # For the by-path, I will need to do a simple ls /dev/tape/by-path it seems
    # -------------------------------------------------------------------------
    elif '/by-path' in drive_device:
        # OK, we caught the /dev/tape/by-path case
        # ----------------------------------------
        cmd = 'ls -l ' + drive_device
        log('ls command: ' + cmd, 30)
        result = get_shell_result(cmd)
        log_cmd_results(result)
        # The ls command outputs a line feed that needs to be stripped
        # ------------------------------------------------------------
        st = re.sub('.* -> .*/n*(st\d+).*', '\\1', result.stdout.rstrip('\n'))
    # Now we use lsscsi to match to the /dev/sg# node required by tapeinfo
    # --------------------------------------------------------------------
    cmd = lsscsi_bin + ' -ug'
    log('lsscsi command: ' + cmd, 30)
    result = get_shell_result(cmd)
    log_cmd_results(result)
    if result.returncode != 0:
        log('ERROR calling: ' + cmd, 20)
    sg_search = re.search('.*' + st + ' .*(/dev/sg\d+)', result.stdout)
    if sg_search:
        sg = sg_search.group(1)
        log('SG node for drive device: ' + drive_device + ' (drive index: ' + drive_index + ') --> ' + sg, 30)
        return sg
    else:
        log('Failed to identify an sg node device for drive device ' + drive_device, 30)
        return 1

def do_checkdrive():
    'Given a tape drive /dev/sg# node, check tapeinfo output, call do_clean if "clean drive" alerts exist.'
    log('In function: do_checkdrive()', 50)
    # First, we need to check and see if we have any cleaning tapes in the library
    # ----------------------------------------------------------------------------
    cln_tapes = chk_for_cln_tapes()
    if auto_clean and len(cln_tapes) == 0:
        # Return to the do_unload function with 1 because we cannot clean a
        # drive device without a cleaning tape, but the do_unload function that
        # called us has already successfully unloaded the tape before it called
        # us and it needs to exit cleanly so the SD sees a 0 return code and
        # can continue.
        # ---------------------------------------------------------------------
        return 1

    # Next, we need the drive device's /dev/sg# node required by tapeinfo
    # -------------------------------------------------------------------
    sg = do_get_sg_node()
    if sg == 1:
        # Return to the do_unload function with 1 because we cannot run
        # tapeinfo without an sg node, but the do_unload function that called
        # us has already successfully unloaded the tape before it called us and
        # it needs to exit cleanly so the SD sees a 0 return code and can
        # continue.
        # ---------------------------------------------------------------------
        return 1

    # Call tapeinfo and parse for alerts
    # ----------------------------------
    cmd = tapeinfo_bin + ' -f ' + sg
    log('Checking drive with tapeinfo utility.', 20)
    log('tapeinfo command: ' + cmd, 30)
    result = get_shell_result(cmd)
    log_cmd_results(result)
    if result.returncode != 0:
        log('ERROR calling: ' + cmd, 20)
    tapealerts = re.findall('TapeAlert\[(\d+)\]: +(.*)', result.stdout)
    if len(tapealerts) > 0:
        clean_drive = False
        log('WARN: Found ' + str(len(tapealerts)) + ' tape alert' + ('s' if len(tapealerts) > 1 else '') \
            + ' for drive device ' + drive_device + ' (' + sg + '):', 20)
        for alert in tapealerts:
            log('      [' + alert[0] + ']: ' + alert[1], 20)
        for cln_code in cln_codes:
            if any(cln_code in i for i in tapealerts):
                clean_drive = True
                # Stop checking as soon as we find one
                # ------------------------------------
                break
        if clean_drive:
            if auto_clean:
                log('Drive requires cleaning and the \'auto_clean\' variable is True. Calling do_clean() function.', 20)
                do_clean(cln_tapes)
            else:
                log('WARN: Drive requires cleaning but the \'auto_clean\' variable is False. Skipping cleaning.', 20)
        else:
            log('No "Drive needs cleaning" tape alerts detected.', 20)
    else:
        log('No tape alerts detected.', 20)
    # Unless we have some major issue here, we
    # need to just return to the do_unload function
    # ---------------------------------------------
    return 0

def do_load(slt = None, drv_dev = None, drv_idx = None, vol = None, cln = False):
    'Load a tape from a slot to a drive.'
    log('In function: do_load()', 50)
    if slt is None:
        slt = slot
    if drv_dev is None:
        drv_dev = drive_device
    if drv_idx is None:
        drv_idx = drive_index
    if vol is None:
        vol = volume
    # TODO:
    # If we are loading a volume from an empty slot, we need
    # to try to get the volume name from a loaded drive too.
    # ------------------------------------------------------
    cmd = mtx_bin + ' -f ' + chgr_device + ' load ' + slt + ' ' + drv_idx
    log('Loading volume' + (' (' + vol + ')' if vol != '' else '') + ' to drive device ' + drv_dev \
         + ' (drive index: ' + drv_idx + ')' + ' from slot ' + slt + '.', 20)
    log('mtx command: ' + cmd, 30)
    result = get_shell_result(cmd)
    log_cmd_results(result)
    if result.returncode != 0:
        log('ERROR calling: ' + cmd, 20)
        fail_txt = 'Failed to load drive device ' + drv_dev + ' (drive index: ' + drv_idx + ') ' \
            + ('with volume (' + vol + ') ' if vol != '' else '') + 'from slot ' + slt + '.'
        log(fail_txt + ' Err: ' + result.stderr.rstrip('\n'), 20)
        log('Exiting with return code ' + str(result.returncode), 20)
        # The SD will print this stdout after the 'Result=' in the job log
        # ----------------------------------------------------------------
        print(fail_txt + ' Err: ' + result.stderr)
        sys.exit(result.returncode)
    # If we are loading a cleaning tape, do the clean_wait
    # waiting here instead of the load_sleep time
    # ----------------------------------------------------
    if cln:
        log('A cleaning tape was just loaded. Will wait (' + clean_wait + ') \'clean_wait\' seconds, then unload it.', 20)
        sleep(int(clean_wait))
        log('Done waiting (' + clean_wait + ') \'clean_wait\' seconds', 30)
        do_unload(slt, drv_dev, drv_idx, vol, cln = True)
    else:
        # Sleep load_sleep seconds after the drive signals it is ready
        # ------------------------------------------------------------
        if int(load_sleep) != 0:
            log('Sleeping for \'load_sleep\' time of ' + load_sleep + ' seconds to let the drive settle.', 20)
            sleep(int(load_sleep))
    if not cln:
        return do_wait_for_drive()

def do_unload(slt = None, drv_dev = None, drv_idx = None, vol = None, cln = False):
    'Unload a tape from a drive to a slot.'
    log('In function: do_unload()', 50)
    if slt is None:
        slt = slot
    if drv_dev is None:
        drv_dev = drive_device
    if drv_idx is None:
        drv_idx = drive_index
    if vol is None:
        vol = volume
    # TODO
    # waa - 202305189 - The 'mt' offline command when issued to a
    #                   drive that is empty hangs for about 2 minutes.
    #                   At least on an mhVTL drive.
    #                   This needs to be tested on a real tape drive.
    #                   Maybe a 'loaded' command should be used to
    #                   test first, and skip the offline/unload
    #                   commands if the drive is already empty.
    # ---------------------- -----------------------------------------
    if offline:
        log('The \'offline\' variable is True. Sending drive device ' + drv_dev + ' offline command before unloading it.', 30)
        cmd = mt_bin + ' -f ' + drv_dev + ' offline'
        log('mt command: ' + cmd, 30)
        result = get_shell_result(cmd)
        log_cmd_results(result)
        if result.returncode != 0:
            log('ERROR calling: ' + cmd, 20)
        if int(offline_sleep) != 0:
            log('Sleeping for \'offline_sleep\' time of ' + offline_sleep + ' seconds to let the drive settle before unloading it.', 20)
            sleep(int(offline_sleep))
    cmd = mtx_bin + ' -f ' + chgr_device + ' unload ' + slt + ' ' + drv_idx
    log('Unloading volume' + (' (' + vol + ')' if vol != '' else '') + ' from drive device ' \
         + drv_dev + ' (drive index: ' + drv_idx + ')' + ' to slot ' + slt + '.', 20)
    log('mtx command: ' + cmd, 30)
    result = get_shell_result(cmd)
    log_cmd_results(result)
    if result.returncode != 0:
        log('ERROR calling: ' + cmd, 20)
        fail_txt = 'Failed to unload drive device ' + drv_dev + ' (drive index: ' + drv_idx + ') ' \
                 + ('with volume (' + vol + ') ' if vol != '' else '') + 'to slot ' + slt + '.'
        log(fail_txt + ' Err: ' + result.stderr, 20)
        log('Exiting with return code ' + str(result.returncode), 20)
        # The SD will print this stdout after the 'Result=' in the job log
        # ----------------------------------------------------------------
        print(fail_txt + ' Err: ' + result.stderr)
    else:
        log('Successfully unloaded volume ' + ('(' + vol + ') ' if vol != '' else '') \
            + 'from drive device ' + drv_dev + ' (drive index: ' + drv_idx + ') to slot ' + slt + '.', 20)
        # After successful unload, check to see if the tape drive should be cleaned.
        # We need to intercept the process here, before we exit from the unload,
        # otherwise the SD will move on and try to load the next tape.
        # Additionally when unloading a cleaning tape, we call do_unload
        # with 'cln = True' so we do not end up in any loops - especially if the
        # drive still reports it needs cleaning after it has been cleaned.
        # ---------------------------------------------------------------------------
        if cln:
            log('A cleaning tape was just unloaded. Skipping tapeinfo tests.', 30)
        elif chk_drive:
            log('The chk_drive variable is True. Calling do_checkdrive() function.', 20)
            checkdrive = do_checkdrive()
            if checkdrive == 1:
                # I think there is nothing to do here. We could not get an sg
                # node, or there are no cleaning tapes in the library, so we
                # cannot run tapeinfoi but the drive has been successfully
                # unloaded, so we just need to exit cleanly here.
                # -----------------------------------------------------------
                log('Exiting do_unload volume ' + ('(' + vol + ')' if vol != '' else '') + ' with return code ' + str(result.returncode), 20)
                return 0
        else:
            log('The chk_drive variable is False. Skipping tapeinfo tests.', 20)
        log('Exiting do_unload volume ' + ('(' + vol + ')' if vol != '' else '') + ' with return code ' + str(result.returncode), 20)
    return result.returncode

def do_transfer():
    'Transfer from one slot to another.'
    # The SD will send the destination slot in the
    # 'drive_device' position on the command line
    # --------------------------------------------
    log('In function: do_transfer()', 50)
    cmd = mtx_bin + ' -f ' + chgr_device + ' transfer ' + slot + ' ' + drive_device
    log('Transferring volume ' + ('(' + volume[0] + ') ' if volume[0] != '' else '(EMPTY) ') + 'from slot '
        + slot + ' to slot ' + drive_device + (' containing volume (' + volume[1] + ')' if volume[1] != '' else '' ) + '.', 20)
    if volume[0] == '' or volume[1] != '':
       log('This operation will fail!', 20)
       log('Not even going to attempt it!', 20)
       log('Exiting with return code 1', 20)
       sys.exit(1)
    else:
       log('mtx command: ' + cmd, 30)
       result = get_shell_result(cmd)
       log_cmd_results(result)
       if result.returncode != 0:
           log('ERROR calling: ' + cmd, 20)
           log('Unsuccessfully transferred volume ' + ('(' + volume[0] + ') ' if volume[0] != '' else '(EMPTY) ') + 'from slot '
               + slot + ' to slot ' + drive_device + (' containing volume (' + volume[1] + ')' if volume[1] != '' else '' ) + '.', 20)
           log('Exiting with return code ' + str(result.returncode), 20)
           return result.returncode
       else:
           log('Successfully transferred volume ' + ('(' + volume[0] + ') ' if volume[0] != '' else '(EMPTY) ') \
               + 'from slot ' + slot + ' to slot ' + drive_device + '.', 20)
           log('Exiting with return code ' + str(result.returncode), 20)
           return 0

# ================
# BEGIN the script
# ================
# Assign docopt doc string variable
# ---------------------------------
args = docopt(doc_opt_str, version='\n' + progname + ' - v' + version + '\n' + reldate + '\n')

# Check for and parse the configuration file first
# ------------------------------------------------
if args['--config'] is not None:
    config_file = args['--config']
    config_section = args['--section']
    if not os.path.exists(config_file) or not os.access(config_file, os.R_OK):
        print('\n' + print_opt_errors('config'))
        usage()
    else:
        try:
            config = ConfigParser(inline_comment_prefixes=('# ', ';'), interpolation=BasicInterpolation())
            config.read(config_file)
            # Create 'config_dict' dictionary from config file
            # ------------------------------------------------
            config_dict = dict(config.items(config_section))
        except Exception as err:
            print('  - An exception has occurred while reading configuration file: ' + str(err))
            print('\n' + print_opt_errors('section'))
            sys.exit(1)

    # For each key in the config_dict dictionary, make
    # its key name into a global variable and assign it the key's dictionary value.
    # https://www.pythonforbeginners.com/basics/convert-string-to-variable-name-in-python
    # -----------------------------------------------------------------------------------
    myvars = vars()
    for k, v in config_dict.items():
        if k in cfg_file_true_false_lst:
            # Convert all the True/False strings to booleans on the fly
            # ---------------------------------------------------------
            # If any lower(dictionary) true/false variable
            # is not 'true', then it is set to False.
            # ----------------------------------------------
            if v.lower() == 'true':
                config_dict[k] = True
            else:
                config_dict[k] = False
        # Set the global variable
        # -----------------------
        myvars[k] = config_dict[k]

# Assign variables from args set
# ------------------------------
mtx_cmd = args['<mtx_cmd>']
chgr_device = args['<chgr_device>']
drive_device = args['<drive_device>']
drive_index = args['<drive_index>']
slot = args['<slot>']
jobid = args['<jobid>']
jobname = args['<jobname>']

# If debug is enabled, log all variables to log file
# --------------------------------------------------
log('----------[ Starting ' + sys.argv[0] + ' ]----------', 10)
log('Config File: ' + args['--config'], 10)
log('Config Section: ' + args['--section'], 10)
log('Changer ID: ' + (chgr_name if chgr_name else 'No chgr_name specified'), 10)
log('Job Name: ' + (jobname if jobname is not None else 'No Job Name specified'), 10)
log('Changer Device: ' + chgr_device, 10)
log('Drive Device: ' + drive_device, 10)
log('Command: ' + mtx_cmd, 10)
log('Drive Index: ' + drive_index, 10)
log('Slot: ' + slot, 10)
log('----------', 10)

# Check the OS to assign the 'ready' variable
# to know when a drive is loaded and ready.
# -------------------------------------------
ready = get_ready_str()

# Check to see if the operation can/should log volume
# names. If yes, then call the getvolname function
# ---------------------------------------------------
if mtx_cmd in ('load', 'loaded', 'unload', 'transfer'):
    volume = do_getvolname()

# Call the appropriate function based on the mtx_cmd
# --------------------------------------------------
if mtx_cmd == 'list':
    print(do_list())
elif mtx_cmd == 'listall':
   print(do_listall())
elif mtx_cmd == 'slots':
    print(do_slots())
elif mtx_cmd == 'loaded':
    print(do_loaded())
elif mtx_cmd == 'load':
    result = do_load()
    sys.exit(result)
elif mtx_cmd == 'unload':
    result = do_unload()
    sys.exit(result)
elif mtx_cmd == 'transfer':
   do_transfer()
else:
    print('\n' + print_opt_errors('command'))
    usage()

