from config import C
from rich import print
class Logger:
    def __init__(self):
        self.enabled = C.logging.get('enabled', True)
    
    def log(self, message):
        if self.enabled:
            print(message)

logger = Logger()
