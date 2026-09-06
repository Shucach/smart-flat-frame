import subprocess

from Classes.CreateResponse import CreateResponse


class FrameControl:
    """Drives the unit that paints the gallery onto the frame panel."""

    CONTROL = '/usr/local/bin/slideshowctl'
    TIMEOUT = 60

    def restart(self) -> CreateResponse:
        """Restarts the slideshow so it picks up whatever is on disk right now.

        `fbi` reads its picture list once, at startup, so a freshly uploaded photo
        only reaches the frame after this.
        """
        code, output = self.__control('restart')

        if code != 0:
            return CreateResponse().set_message(output or 'Slideshow could not be restarted').failed()

        return CreateResponse().set_data(self.__state()).success()

    def status(self) -> CreateResponse:
        return CreateResponse().set_data(self.__state()).success()

    def __state(self) -> dict:
        code, state = self.__control('status')

        return {
            'active': code == 0,
            'state': state or 'unknown',
        }

    def __control(self, command):
        """Returns the exit code and combined output, or `None` if it could not run."""
        try:
            process = subprocess.run(
                ['sudo', '-n', self.CONTROL, command],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=self.TIMEOUT,
            )
        except (OSError, subprocess.SubprocessError) as error:
            return None, str(error)

        return process.returncode, process.stdout.decode('utf-8', 'replace').strip()
