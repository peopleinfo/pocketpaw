import multiprocessing

from ..config import settings
from ..utils.logger import logger


class G4FApiService:
    """Runs the G4F built-in API server in a child process."""

    def __init__(self):
        self.process = None

    def start(self):
        if self.process and self.process.is_alive():
            logger.info("G4F API server is already running.")
            return

        try:
            from g4f.api import run_api

            logger.info(
                f"Starting G4F API server on {settings.host}:{settings.port}"
            )
            self.process = multiprocessing.Process(
                target=run_api,
                kwargs={"bind": f"{settings.host}:{settings.port}"},
            )
            self.process.start()
            logger.info(f"G4F API server started with PID: {self.process.pid}")
        except Exception as e:
            logger.error(f"Failed to start G4F API server: {e}")
            raise

    def stop(self):
        if self.process and self.process.is_alive():
            logger.info("Stopping G4F API server...")
            self.process.terminate()
            self.process.join()
            logger.info("G4F API server stopped.")
        else:
            logger.info("G4F API server is not running.")


g4f_api_service = G4FApiService()
