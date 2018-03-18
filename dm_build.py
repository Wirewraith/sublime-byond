import sublime
import sublime_plugin

import sys
import subprocess
import threading
import os
import time

class ExecDmBuildCommand(sublime_plugin.WindowCommand):

    encoding = 'utf-8'
    killed = False
    proc = None
    panel = None
    panel_lock = threading.Lock()

    def is_enabled(self, kill = False, **kwargs):
        print('CHECKING IS_ENABLED')
        # The Cancel build option should only be available when the process is still running
        # if kill:
        #     return self.proc is not None and self.proc.poll() is None
        # return True
        return self.proc is not None

    def run(self, kill = False, dm_launch = False, **kwargs):
        if kill:
            self.kill()
            return

        vars = self.window.extract_variables()
        working_dir = vars['project_path']

        # A lock is used to ensure only one thread is touching the output panel at a time
        with self.panel_lock:
            # Creating the panel implicitly clears any previous contents
            self.panel = self.window.create_output_panel('dm_build')

            # Enable result navigation. The result_base_dir sets the
            # path to resolve relative file names against.
            settings = self.panel.settings()
            settings.set(
                'result_file_regex',
                r'^((?:.*?)\.(?:.*?)):(.*?):()(.*?)$'
            )
            settings.set('result_base_dir', working_dir)
            settings.set('syntax', 'Packages/sublime-DM-2/DM.tmLanguage')

            self.window.run_command('show_panel', {'panel': 'output.dm_build'})

        if self.proc is not None:
            self.kill()

        self.start_time = time.time()

        # Hide the console window on Windows
        startupInfo = None
        if os.name == 'nt':
            startupInfo = subprocess.STARTUPINFO()
            startupInfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        if dm_launch:
            cmd = [self.get_setting('installation_path') + self.get_setting(dm_launch + '_executable')] + [self.get_build_file(working_dir, '.dmb')] + ['-trusted']

            if dm_launch == 'seeker':
                self.queue_write('[Running project in DreamSeeker...]')
            elif dm_launch == 'daemon':
                self.queue_write('[Running project in DreamDaemon...]')

        else:
            cmd = [self.get_setting('installation_path') + self.get_setting('compiler_executable')] + [self.get_build_file(working_dir, '.dme')]

        self.proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            startupinfo=startupInfo,
            cwd=working_dir,
            shell=True
        )
        self.killed = False

        threading.Thread(
            target=self.read_handle,
            args=(self.proc.stdout,)
        ).start()

    def read_handle(self, handle):
        chunk_size = 2 ** 13
        out = b''
        while True:
            try:
                data = os.read(handle.fileno(), chunk_size)
                # If exactly the requested number of bytes was
                # read, there may be more data, and the current
                # data may contain part of a multibyte char
                out += data
                if len(data) == chunk_size:
                    continue
                if data == b'' and out == b'':
                    raise IOError('EOF')
                # We pass out to a function to ensure the
                # timeout gets the value of out right now,
                # rather than a future (mutated) version
                characters = out.decode(self.encoding)
                characters = characters.replace('\r\n', '\n').replace('\r', '\n')
                self.queue_write(characters)
                if data == b'':
                    raise IOError('EOF')
                out = b''
            except (UnicodeDecodeError) as e:
                msg = 'Error decoding output using %s - %s'
                self.queue_write(msg  % (self.encoding, str(e)))
                break
            except (IOError):
                if self.killed:
                    msg = 'Cancelled'
                else:
                    elapsed = time.time() - self.start_time
                    msg = 'Finished in %.1fs' % elapsed
                    sublime.status_message('Build finished')
                self.queue_write('\n[%s]' % msg)
                break

    def queue_write(self, text):
        sublime.set_timeout(lambda: self.do_write(text), 1)

    def do_write(self, text):
        with self.panel_lock:
            self.panel.run_command('append', {'characters': text, 'scroll_to_end': True})

    def get_setting(self, config):
        settings = sublime.load_settings('Preferences.sublime-settings')

        if settings.get('dm_' + config):
            return settings.get('dm_' + config)
        else:
            settings = sublime.load_settings('DM.sublime-settings')
            return settings.get('dm_' + config)

    def get_build_file(self, working_dir, ext):
        for root, dirs, files in os.walk(working_dir):
            # Ignore dotfiles/dotfolders
            files = [f for f in files if not f[0] == '.']
            dirs[:] = [d for d in dirs if not d[0] == '.']
            for file in files:
                if file.lower().endswith(ext):
                    filePath = os.path.join(root, file)
                    return filePath

    def kill(self):
        if not self.killed and self.proc is not None:
            self.killed = True
            if sys.platform == "win32":
                # terminate would not kill process opened by the shell cmd.exe,
                # it will only kill cmd.exe leaving the child running
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                subprocess.Popen(
                    "taskkill /T /F /PID " + str(self.proc.pid),
                    startupinfo=startupinfo)
            else:
                self.proc.terminate()
            self.proc = None