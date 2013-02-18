#
# Copyright (C) 2013  Red Hat, Inc.
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# the GNU General Public License v.2, or (at your option) any later version.
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY expressed or implied, including the implied warranties of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General
# Public License for more details.  You should have received a copy of the
# GNU General Public License along with this program; if not, write to the
# Free Software Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.  Any Red Hat trademarks that are incorporated in the
# source code or documentation are not subject to the GNU General Public
# License and may only be used or replicated with the express permission of
# Red Hat, Inc.
#
# Red Hat Author(s): Stef Walter <stefw@redhat.com>
#                    Vratislav Podzimek <vpodzime@redhat.com>
#

from pyanaconda import iutil
from pyanaconda.addons import AddonData
from pyanaconda.constants import ROOT_PATH
from pykickstart.errors import KickstartValueError, KickstartParseError

import getopt
import pipes
import shlex

import logging
log = logging.getLogger("anaconda")

# TODO: enable translations
_ = lambda x: x

__all__ = ["RealmData"]

class RealmData(AddonData):
    def __init__(self, name):
        """
        @param name: name of the addon
        @type name: str

        """

        AddonData.__init__(self, name)
        self.join_realm = None
        self.join_args = []
        self.after = []
        self.discover_options = []
        self.discovered = ""
        self.packages = []

    def __str__(self):
        """
        What should end up between %addon and %end lines in the resulting
        kickstart file, i.e. string representation of the stored data.

        """

        ret = ""
        if self.join_args:
            args = [pipes.quote(arg) for arg in self.join_args]
            ret += "realm join %s" % " ".join(self.join_args)
        for (command, args) in self.after:
            args = [pipes.quote(arg) for arg in args]
            ret += "realm %s %s" % (command, " ".join(args))

        return ret

    def handle_line(self, line):
        """
        The handle_line method that is called with every line from this addon's
        %addon section of the kickstart file.

        @param line: a single line from the %addon section
        @type line: str

        """

        self._parseArguments(line.strip())

    def setup(self, storage, ksdata, instclass):
        """
        The setup method that should make changes to the runtime environment
        according to the data stored in this object.

        @param storage: object storing storage-related information
                        (disks, partitioning, bootloader, etc.)
        @type storage: blivet.Blivet instance
        @param ksdata: data parsed from the kickstart file and set in the
                       installation process
        @type ksdata: pykickstart.base.BaseHandler instance
        @param instclass: distribution-specific information
        @type instclass: pyanaconda.installclass.BaseInstallClass

        """

        self.discover()
        for package in self.packages:
            if package not in ksdata.packages.packageList:
                ksdata.packages.packageList.append(package)

    def execute(self, storage, ksdata, instclass, users):
        """
        The execute method that should make changes to the installed system. It
        is called only once in the post-install setup phase.

        @see: setup
        @param users: information about created users
        @type users: pyanaconda.users.Users instance

        """

        if not self.discovered:
            return

        pw_args = ["--no-password"]
        for arg in self.join_args:
            if arg.startswith("--no-password") or arg.startswith("--one-time-password"):
                pw_args = []
                break

        args = ["join", "--install", ROOT_PATH, "--verbose"] + pw_args + self.join_args
        try:
            rc = iutil.execWithRedirect("realm", args)
        except RuntimeError as msg:
            log.error("Error running realm %s: %s", args, msg)

        if rc != 0:
            log.error("Command failure: realm %s: %d", args, rc)
            return

        log.info("Joined realm %s", self.join_realm)

        for (command, options) in self.after:
            args = [command, "--install", ROOT_PATH, "--verbose"] + options
            rc = iutil.execWithRedirect("realm", args)
            if rc != 0:
                log.error("Command failure: realm %s: %d", args, rc)

            log.info("Ran realm %s", args)


    def _parseArguments(self, string):
        args = shlex.split(string)
        if not args:
            raise KickstartValueError(_("Missing realm command arguments"))
        command = args.pop(0)
        if command in ("permit", "deny"):
            self._parsePermitOrDeny(command, args)
        elif command == "join":
            self._parseJoin(args)
        else:
            raise KickstartValueError(_("Unsupported realm command: '%s'" % command))

    def _parsePermitOrDeny(self, command, args):
        try:
            opts, remaining = getopt.getopt(args, "av", ("all", "verbose"))
            self.after.append((command, args))
        except getopt.GetoptError, ex:
            raise KickstartValueError(_("Invalid realm arguments: %s") % str(ex))

    def _parseJoin(self, args):
        if self.join_realm:
            raise KickstartParseError(_("The realm command 'join' should only be specified once"))

        try:
            # We only support these args
            opts, remaining = getopt.getopt(args, "", ("client-software=",
                                                       "server-software=",
                                                       "membership-software=",
                                                       "one-time-password=",
                                                       "no-password=",
                                                       "computer-ou="))
        except getopt.GetoptError, ex:
            raise KickstartValueError(_("Invalid realm arguments: %s") % str(ex))

        if len(remaining) != 1:
            raise KickstartValueError(_("Specify one realm to join"))

        # Parse successful, just use this as the join command
        self.join_realm = remaining[0]
        self.join_args = args

        # Build a discovery command
        self.discover_options = []
        for (o, a) in opts:
            if o in ("--client-software", "--server-software", "--membership-software"):
                self.discover_options.append("%s=%s" % (o, a))

    def discover(self):
        if not self.join_realm:
            return

        try:
            args = ["discover", "--verbose", "--install", "/"] + \
                   self.discover_options + [self.join_realm]
            output = iutil.execWithCapture("realm", args, fatal=True)
        except RuntimeError as msg:
            log.error("Error running realm %s: %s", args, msg)
            return
        except OSError as msg:
            # TODO: A lousy way of propagating what will usually be 'no such realm'
            log.error("Error running realm %s: %s", args, msg)
            return

        # Now parse the output for the required software. First line is the
        # realm name, and following lines are information as "name: value"
        self.packages = ["realmd"]
        self.discovered = ""

        lines = output.split("\n")
        if not lines:
            return

        self.discovered = lines.pop(0).strip()
        for line in lines:
            parts = line.split(":", 1)
            if len(parts) == 2 and parts[0].strip() == "required-package":
                self.packages.append(parts[1].strip())

        log.info("Realm %s needs packages %s" %
                 (self.discovered, ", ".join(self.packages)))
