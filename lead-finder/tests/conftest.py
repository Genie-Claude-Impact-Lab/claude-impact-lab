import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import finder
finder.SMTP_CHECK = False   # never contact real mail servers from tests
