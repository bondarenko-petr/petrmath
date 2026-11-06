import os
from pathlib import Path
from .app import create_app

app = create_app(data_dir=os.environ.get('BOARD_DATA_DIR', Path(__file__).with_name('board-data')))
