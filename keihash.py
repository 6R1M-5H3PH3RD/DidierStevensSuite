#!/usr/bin/env python

from __future__ import print_function

__description__ = 'Calculate SSH Key Exchange Init (KEI) hash: KEIHash'
__author__ = 'Didier Stevens'
__version__ = '0.0.1'
__date__ = '2018/10/10'

"""

Source code put in the public domain by Didier Stevens, no Copyright
https://DidierStevens.com
Use at your own risk

History:
  2018/08/23: start
  2018/09/16: continue
  2018/10/09: switched to pcap template
  2018/10/10: cleanup

Todo:
"""

import optparse
import glob
import collections
import time
import sys
import textwrap
import os
import gzip
import fnmatch
import dpkt
import socket
import struct
import hashlib
if sys.version_info[0] < 3:
    import cPickle
else:
    import pickle as cPickle
import atexit
if sys.platform == 'win32' and sys.version_info[0] < 3:
    import win_inet_pton
from contextlib import contextmanager

SSH_PORT = 22
CSV_SEPARATOR = ';'

def PrintManual():
    manual = '''
Manual:

To Be Completed

Calculate SSH Key Exchange Init (KEI) hash: KEIHash

Errors occuring when opening a file are reported (and logged if logging is turned on), and the program moves on to the next file.
Errors occuring when reading & processing a file are reported (and logged if logging is turned on), and the program stops unless option ignoreprocessingerrors is used.

The lines are written to standard output, except when option -o is used. When option -o is used, the lines are written to the filename specified by option -o.
Filenames used with option -o starting with # have special meaning.
#c#example.txt will write output both to the console (stdout) and file example.txt.
#g# will write output to a file with a filename generated by the tool like this: toolname-date-time.txt.
#g#KEYWORD will write output to a file with a filename generated by the tool like this: toolname-KEYWORD-date-time.txt.
Use #p#filename to display execution progress.
To process several files while creating seperate output files for each input file, use -o #s#%f%.result *.
This will create output files with the name of the inputfile and extension .result.
There are several variables available when creating separate output files:
 %f% is the full filename (with directory if present)
 %b% is the base name: the filename without directory
 %d% is the directory
 %r% is the root: the filename without extension
 %ru% is the root made unique by appending a counter (if necessary)
 %e% is the extension
Most options can be combined, like #ps# for example.
#l# is used for literal filenames: if the output filename has to start with # (#example.txt for example), use filename #l##example.txt for example.

'''
    for line in manual.split('\n'):
        print(textwrap.fill(line))

DEFAULT_SEPARATOR = ','
QUOTE = '"'

def PrintError(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)

#Convert 2 Integer If Python 2
def C2IIP2(data):
    if sys.version_info[0] > 2:
        return data
    else:
        return ord(data)

#Convert 2 String If Python 3
def C2SIP3(data):
    if sys.version_info[0] > 2:
        return data.decode('utf8')
    else:
        return data

def File2Strings(filename):
    try:
        f = open(filename, 'r')
    except:
        return None
    try:
        return map(lambda line:line.rstrip('\n'), f.readlines())
    except:
        return None
    finally:
        f.close()

def ProcessAt(argument):
    if argument.startswith('@'):
        strings = File2Strings(argument[1:])
        if strings == None:
            raise Exception('Error reading %s' % argument)
        else:
            return strings
    else:
        return [argument]

# CIC: Call If Callable
def CIC(expression):
    if callable(expression):
        return expression()
    else:
        return expression

# IFF: IF Function
def IFF(expression, valueTrue, valueFalse):
    if expression:
        return CIC(valueTrue)
    else:
        return CIC(valueFalse)

def Serialize(object, filename=None):
    try:
        fPickle = open(filename, 'wb')
    except:
        return False
    try:
        cPickle.dump(object, fPickle, cPickle.HIGHEST_PROTOCOL)
    except:
        return False
    finally:
        fPickle.close()
    return True

def DeSerialize(filename=None):
    if os.path.isfile(filename):
        try:
            fPickle = open(filename, 'rb')
        except:
            return None
        try:
            object = cPickle.load(fPickle)
        except:
            return None
        finally:
            fPickle.close()
        return object
    else:
        return None

class cVariables():
    def __init__(self, variablesstring='', separator=DEFAULT_SEPARATOR):
        self.dVariables = {}
        if variablesstring == '':
            return
        for variable in variablesstring.split(separator):
            name, value = VariableNameValue(variable)
            self.dVariables[name] = value

    def SetVariable(self, name, value):
        self.dVariables[name] = value

    def Instantiate(self, astring):
        for key, value in self.dVariables.items():
            astring = astring.replace('%' + key + '%', value)
        return astring

class cOutput():
    def __init__(self, filenameOption=None):
        self.starttime = time.time()
        self.filenameOption = filenameOption
        self.separateFiles = False
        self.progress = False
        self.console = False
        self.fOut = None
        self.rootFilenames = {}
        if self.filenameOption:
            if self.ParseHash(self.filenameOption):
                if not self.separateFiles and self.filename != '':
                    self.fOut = open(self.filename, 'w')
            elif self.filenameOption != '':
                self.fOut = open(self.filenameOption, 'w')

    def ParseHash(self, option):
        if option.startswith('#'):
            position = self.filenameOption.find('#', 1)
            if position > 1:
                switches = self.filenameOption[1:position]
                self.filename = self.filenameOption[position + 1:]
                for switch in switches:
                    if switch == 's':
                        self.separateFiles = True
                    elif switch == 'p':
                        self.progress = True
                    elif switch == 'c':
                        self.console = True
                    elif switch == 'l':
                        pass
                    elif switch == 'g':
                        if self.filename != '':
                            extra = self.filename + '-'
                        else:
                            extra = ''
                        self.filename = '%s-%s%s.txt' % (os.path.splitext(os.path.basename(sys.argv[0]))[0], extra, self.FormatTime())
                    else:
                        return False
                return True
        return False

    @staticmethod
    def FormatTime(epoch=None):
        if epoch == None:
            epoch = time.time()
        return '%04d%02d%02d-%02d%02d%02d' % time.localtime(epoch)[0:6]

    def RootUnique(self, root):
        if not root in self.rootFilenames:
            self.rootFilenames[root] = None
            return root
        iter = 1
        while True:
            newroot = '%s_%04d' % (root, iter)
            if not newroot in self.rootFilenames:
                self.rootFilenames[newroot] = None
                return newroot
            iter += 1

    def Line(self, line):
        if self.fOut == None or self.console:
            try:
                print(line)
            except UnicodeEncodeError:
                encoding = sys.stdout.encoding
                print(line.encode(encoding, errors='backslashreplace').decode(encoding))
#            sys.stdout.flush()
        if self.fOut != None:
            self.fOut.write(line + '\n')
            self.fOut.flush()

    def LineTimestamped(self, line):
        self.Line('%s: %s' % (self.FormatTime(), line))

    def Filename(self, filename, index, total):
        self.separateFilename = filename
        if self.progress:
            if index == 0:
                eta = ''
            else:
                seconds = int(float((time.time() - self.starttime) / float(index)) * float(total - index))
                eta = 'estimation %d seconds left, finished %s ' % (seconds, self.FormatTime(time.time() + seconds))
            PrintError('%d/%d %s%s' % (index + 1, total, eta, self.separateFilename))
        if self.separateFiles and self.filename != '':
            oFilenameVariables = cVariables()
            oFilenameVariables.SetVariable('f', self.separateFilename)
            basename = os.path.basename(self.separateFilename)
            oFilenameVariables.SetVariable('b', basename)
            oFilenameVariables.SetVariable('d', os.path.dirname(self.separateFilename))
            root, extension = os.path.splitext(basename)
            oFilenameVariables.SetVariable('r', root)
            oFilenameVariables.SetVariable('ru', self.RootUnique(root))
            oFilenameVariables.SetVariable('e', extension)

            self.Close()
            self.fOut = open(oFilenameVariables.Instantiate(self.filename), 'w')

    def Close(self):
        if self.fOut != None:
            self.fOut.close()
            self.fOut = None

class cExpandFilenameArguments():
    def __init__(self, filenames, literalfilenames=False, recursedir=False, checkfilenames=False, expressionprefix=None):
        self.containsUnixShellStyleWildcards = False
        self.warning = False
        self.message = ''
        self.filenameexpressions = []
        self.expressionprefix = expressionprefix
        self.literalfilenames = literalfilenames

        expression = ''
        if len(filenames) == 0:
            self.filenameexpressions = [['', '']]
        elif literalfilenames:
            self.filenameexpressions = [[filename, ''] for filename in filenames]
        elif recursedir:
            for dirwildcard in filenames:
                if expressionprefix != None and dirwildcard.startswith(expressionprefix):
                    expression = dirwildcard[len(expressionprefix):]
                else:
                    if dirwildcard.startswith('@'):
                        for filename in ProcessAt(dirwildcard):
                            self.filenameexpressions.append([filename, expression])
                    elif os.path.isfile(dirwildcard):
                        self.filenameexpressions.append([dirwildcard, expression])
                    else:
                        if os.path.isdir(dirwildcard):
                            dirname = dirwildcard
                            basename = '*'
                        else:
                            dirname, basename = os.path.split(dirwildcard)
                            if dirname == '':
                                dirname = '.'
                        for path, dirs, files in os.walk(dirname):
                            for filename in fnmatch.filter(files, basename):
                                self.filenameexpressions.append([os.path.join(path, filename), expression])
        else:
            for filename in list(collections.OrderedDict.fromkeys(sum(map(self.Glob, sum(map(ProcessAt, filenames), [])), []))):
                if expressionprefix != None and filename.startswith(expressionprefix):
                    expression = filename[len(expressionprefix):]
                else:
                    self.filenameexpressions.append([filename, expression])
            self.warning = self.containsUnixShellStyleWildcards and len(self.filenameexpressions) == 0
            if self.warning:
                self.message = "Your filename argument(s) contain Unix shell-style wildcards, but no files were matched.\nCheck your wildcard patterns or use option literalfilenames if you don't want wildcard pattern matching."
                return
        if self.filenameexpressions == [] and expression != '':
            self.filenameexpressions = [['', expression]]
        if checkfilenames:
            self.CheckIfFilesAreValid()

    def Glob(self, filename):
        if not ('?' in filename or '*' in filename or ('[' in filename and ']' in filename)):
            return [filename]
        self.containsUnixShellStyleWildcards = True
        return glob.glob(filename)

    def CheckIfFilesAreValid(self):
        valid = []
        doesnotexist = []
        isnotafile = []
        for filename, expression in self.filenameexpressions:
            hashfile = False
            try:
                hashfile = FilenameCheckHash(filename, self.literalfilenames)[0] == FCH_DATA
            except:
                pass
            if filename == '' or hashfile:
                valid.append([filename, expression])
            elif not os.path.exists(filename):
                doesnotexist.append(filename)
            elif not os.path.isfile(filename):
                isnotafile.append(filename)
            else:
                valid.append([filename, expression])
        self.filenameexpressions = valid
        if len(doesnotexist) > 0:
            self.warning = True
            self.message += 'The following files do not exist and will be skipped: ' + ' '.join(doesnotexist) + '\n'
        if len(isnotafile) > 0:
            self.warning = True
            self.message += 'The following files are not regular files and will be skipped: ' + ' '.join(isnotafile) + '\n'

    def Filenames(self):
        if self.expressionprefix == None:
            return [filename for filename, expression in self.filenameexpressions]
        else:
            return self.filenameexpressions

def ToString(value):
    if isinstance(value, str):
        return value
    else:
        return str(value)

def Quote(value, separator, quote):
    value = ToString(value)
    if separator in value or value == '':
        return quote + value + quote
    else:
        return value

def MakeCSVLine(row, separator, quote):
    return separator.join([Quote(value, separator, quote) for value in row])

class cLogfile():
    def __init__(self, keyword, comment):
        self.starttime = time.time()
        self.errors = 0
        if keyword == '':
            self.oOutput = None
        else:
            self.oOutput = cOutput('%s-%s-%s.log' % (os.path.splitext(os.path.basename(sys.argv[0]))[0], keyword, self.FormatTime()))
        self.Line('Start')
        self.Line('UTC', '%04d%02d%02d-%02d%02d%02d' % time.gmtime(time.time())[0:6])
        self.Line('Comment', comment)
        self.Line('Args', repr(sys.argv))
        self.Line('Version', __version__)
        self.Line('Python', repr(sys.version_info))
        self.Line('Platform', sys.platform)
        self.Line('CWD', repr(os.getcwd()))

    @staticmethod
    def FormatTime(epoch=None):
        if epoch == None:
            epoch = time.time()
        return '%04d%02d%02d-%02d%02d%02d' % time.localtime(epoch)[0:6]

    def Line(self, *line):
        if self.oOutput != None:
            self.oOutput.Line(MakeCSVLine((self.FormatTime(), ) + line, DEFAULT_SEPARATOR, QUOTE))

    def LineError(self, *line):
        self.Line('Error', *line)
        self.errors += 1

    def Close(self):
        if self.oOutput != None:
            self.Line('Finish', '%d error(s)' % self.errors, '%d second(s)' % (time.time() - self.starttime))
            self.oOutput.Close()

def AnalyzeFileError(filename):
    PrintError('Error opening file %s' % filename)
    PrintError(sys.exc_info()[1])
    try:
        if not os.path.exists(filename):
            PrintError('The file does not exist')
        elif os.path.isdir(filename):
            PrintError('The file is a directory')
        elif not os.path.isfile(filename):
            PrintError('The file is not a regular file')
    except:
        pass

@contextmanager
def PcapFile(filename, oLogfile):
    if filename == '':
        fIn = sys.stdin
    elif os.path.splitext(filename)[1].lower() == '.gz':
        try:
            fIn = gzip.GzipFile(filename, 'rb')
        except:
            AnalyzeFileError(filename)
            oLogfile.LineError('Opening file %s %s' % (filename, repr(sys.exc_info()[1])))
            fIn = None
    else:
        try:
            fIn = open(filename, 'rb')
        except:
            AnalyzeFileError(filename)
            oLogfile.LineError('Opening file %s %s' % (filename, repr(sys.exc_info()[1])))
            fIn = None

    if fIn != None:
        oLogfile.Line('Success', 'Opening file %s' % filename)

    yield fIn

    if fIn != None:
        if sys.exc_info()[1] != None:
            oLogfile.LineError('Reading file %s %s' % (filename, repr(sys.exc_info()[1])))
        if fIn != sys.stdin:
            fIn.close()

def ParseString(data):
    if len(data) < 4:
        return None, None
    length = struct.unpack('>I', data[0:4])[0]
    if len(data) < length:
        return None, None
    return '%d-%s' % (length, C2SIP3(data[4:4 + length])), data[4 + length:]

def ParseKEI(data):
    length, padding = struct.unpack('>IB', data[0:5])
    if length != len(data) - 4:
        return None
    strings = data[22:-padding - 5]
    results = []
    while len(strings) > 0:
        result, strings = ParseString(strings)
        if result == None:
            return None
        results.append(result)
    return ';'.join(results)

def IP2String(address):
    try:
        return socket.inet_ntop(socket.AF_INET, address)
    except ValueError:
        return socket.inet_ntop(socket.AF_INET6, address)

def ProcessPcapFile(filename, oOutput, oLogfile, options):
    with PcapFile(filename, oLogfile) as fIn:
        try:
            dConnections = {}
            for timestamp, buffer in dpkt.pcap.Reader(fIn):
                # ----- Put your line processing code here -----
                #oOutput.Line(line)
                try:
                    frame = dpkt.ethernet.Ethernet(buffer)
                except:
                    continue

                if not isinstance(frame.data, dpkt.ip.IP) or not isinstance(frame.data.data, dpkt.tcp.TCP):
                    continue
                ipPacket = frame.data
                tcpPacket = ipPacket.data

                if not (tcpPacket.dport == SSH_PORT or tcpPacket.sport == SSH_PORT or options.allports):
                    continue

                if tcpPacket.sport < tcpPacket.dport:
                    connectionid = '%s:%d-%s:%d' % (IP2String(ipPacket.src), tcpPacket.sport, IP2String(ipPacket.dst), tcpPacket.dport)
                else:
                    connectionid = '%s:%d-%s:%d' % (IP2String(ipPacket.dst), tcpPacket.dport, IP2String(ipPacket.src), tcpPacket.sport)

                if tcpPacket.flags == 2:
                    dConnections[connectionid] = {'SYN': True, 'sport': tcpPacket.sport, 'dport': tcpPacket.dport}
                    continue

                if len(tcpPacket.data) == 0:
                    continue

                if connectionid in dConnections:
                    if not 'CLIENT_BANNER' in dConnections[connectionid]:
                        if dConnections[connectionid]['dport'] == tcpPacket.dport:
                            dConnections[connectionid]['CLIENT_BANNER'] = tcpPacket.data
                            continue
                    if not 'SERVER_BANNER' in dConnections[connectionid]:
                        if dConnections[connectionid]['dport'] == tcpPacket.sport:
                            dConnections[connectionid]['SERVER_BANNER'] = tcpPacket.data
                            continue
                    if 'CLIENT_BANNER' in dConnections[connectionid] and 'SERVER_BANNER' in dConnections[connectionid] and len(tcpPacket.data) > 5 and C2IIP2(tcpPacket.data[5]) == 0x14:
                        if not 'CLIENT_KEY_EXCHANGE_INIT' in dConnections[connectionid] and dConnections[connectionid]['dport'] == tcpPacket.dport:
                            dConnections[connectionid]['CLIENT_KEY_EXCHANGE_INIT'] = tcpPacket.data
                            if tcpPacket.flags & 0x08:
                                dConnections[connectionid]['PUSH'] = True
                        elif not 'SERVER_KEY_EXCHANGE_INIT' in dConnections[connectionid] and dConnections[connectionid]['dport'] == tcpPacket.sport:
                            dConnections[connectionid]['SERVER_KEY_EXCHANGE_INIT'] = tcpPacket.data
                    elif 'CLIENT_BANNER' in dConnections[connectionid] and 'SERVER_BANNER' in dConnections[connectionid] and 'CLIENT_KEY_EXCHANGE_INIT' in dConnections[connectionid] and dConnections[connectionid]['dport'] == tcpPacket.dport and 'PUSH' in dConnections[connectionid] and dConnections[connectionid]['PUSH']:
                        dConnections[connectionid]['CLIENT_KEY_EXCHANGE_INIT'] += tcpPacket.data
                        dConnections[connectionid]['PUSH'] = False
                    if 'CLIENT_BANNER' in dConnections[connectionid] and 'SERVER_BANNER' in dConnections[connectionid] and 'CLIENT_KEY_EXCHANGE_INIT' in dConnections[connectionid] and 'SERVER_KEY_EXCHANGE_INIT' in dConnections[connectionid]:
                        row = [connectionid]
                        row = ['CLIENT']
                        row.append(repr(C2SIP3(dConnections[connectionid]['CLIENT_BANNER']).rstrip('\r\n')))
                        clientData = ParseKEI(dConnections[connectionid]['CLIENT_KEY_EXCHANGE_INIT'])
                        if clientData != None:
                            row.append(hashlib.md5(clientData.encode()).hexdigest())
                            row.append(clientData)
                            oOutput.Line((MakeCSVLine(row, CSV_SEPARATOR, QUOTE)))
                        row = ['SERVER']
                        row.append(repr(C2SIP3(dConnections[connectionid]['SERVER_BANNER']).rstrip('\r\n')))
                        serverData = ParseKEI(dConnections[connectionid]['SERVER_KEY_EXCHANGE_INIT'])
                        if serverData != None:
                            row.append(hashlib.md5(serverData.encode()).hexdigest())
                            row.append(serverData)
                            oOutput.Line((MakeCSVLine(row, CSV_SEPARATOR, QUOTE)))
                        del(dConnections[connectionid])
                # ----------------------------------------------
        except:
            oLogfile.LineError('Processing file %s %s' % (filename, repr(sys.exc_info()[1])))
            if sys.exc_info()[0] == KeyboardInterrupt:
                raise
            if not options.ignoreprocessingerrors:
                raise
            if sys.version_info[0] < 3:
                sys.exc_clear()

def InstantiateCOutput(options):
    filenameOption = None
    if options.output != '':
        filenameOption = options.output
    return cOutput(filenameOption)

def ProcessPcapFiles(filenames, oLogfile, options):
    if options.processedfilesdb != None:
        data = DeSerialize(options.processedfilesdb)
        if data == None:
            dProcessedFiles = {}
        else:
            dProcessedFiles = data[0]
        atexit.register(Serialize, [dProcessedFiles], options.processedfilesdb)
    else:
        dProcessedFiles = {}

    oOutput = InstantiateCOutput(options)

    for index, filename in enumerate(filenames):
        if not filename in dProcessedFiles:
            oOutput.Filename(filename, index, len(filenames))
            ProcessPcapFile(filename, oOutput, oLogfile, options)
            dProcessedFiles[filename] = time.time()

    oOutput.Close()

#    if options.processedfilesdb != None:
#        Serialize([dProcessedFiles], options.processedfilesdb)

def Main():
    moredesc = '''

Arguments:
@file: process each file listed in the text file specified
wildcards are supported

Source code put in the public domain by Didier Stevens, no Copyright
Use at your own risk
https://DidierStevens.com'''

    oParser = optparse.OptionParser(usage='usage: %prog [options] [[@]file ...]\n' + __description__ + moredesc, version='%prog ' + __version__)
    oParser.add_option('-m', '--man', action='store_true', default=False, help='Print manual')
    oParser.add_option('-o', '--output', type=str, default='', help='Output to file (# supported)')
    oParser.add_option('-a', '--allports', action='store_true', default=False, help='Process packets for all ports, not just 22')
    oParser.add_option('--literalfilenames', action='store_true', default=False, help='Do not interpret filenames')
    oParser.add_option('--recursedir', action='store_true', default=False, help='Recurse directories (wildcards and here files (@...) allowed)')
    oParser.add_option('--checkfilenames', action='store_true', default=False, help='Perform check if files exist prior to file processing')
    oParser.add_option('--processedfilesdb', default=None, help='File database (pickle) of processed files')
    oParser.add_option('--logfile', type=str, default='', help='Create logfile with given keyword')
    oParser.add_option('--logcomment', type=str, default='', help='A string with comments to be included in the log file')
    oParser.add_option('--ignoreprocessingerrors', action='store_true', default=False, help='Ignore errors during file processing')
    (options, args) = oParser.parse_args()

    if options.man:
        oParser.print_help()
        PrintManual()
        return

    oLogfile = cLogfile(options.logfile, options.logcomment)

    oExpandFilenameArguments = cExpandFilenameArguments(args, options.literalfilenames, options.recursedir, options.checkfilenames)
    oLogfile.Line('FilesCount', str(len(oExpandFilenameArguments.Filenames())))
    oLogfile.Line('Files', repr(oExpandFilenameArguments.Filenames()))
    if oExpandFilenameArguments.warning:
        PrintError('\nWarning:')
        PrintError(oExpandFilenameArguments.message)
        oLogfile.Line('Warning', repr(oExpandFilenameArguments.message))

    ProcessPcapFiles(oExpandFilenameArguments.Filenames(), oLogfile, options)

    if oLogfile.errors > 0:
        PrintError('Number of errors: %d' % oLogfile.errors)
    oLogfile.Close()

if __name__ == '__main__':
    Main()