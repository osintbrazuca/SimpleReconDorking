"""
Project metadata.

Single source of truth for the strings shown in the banner footer and
substituted into banner art files via the [VERSION] / [DESCRIPTION]
placeholders (see core/banner/asciiart.py).

Note: the default User-Agent literal ('SimpleReconDorking/1') is deliberately
NOT derived from here. core/run_config.py compares each parsed argument
against its argparse default to decide whether the user set it explicitly,
so that literal must stay byte-identical across cli/parser.py,
sources/base.py, core/engine.py and core/run_config.py.
"""

__version__ = '1.0.0'
__description__ = 'Dorking across search engines - operator dorks in, URLs out'
__author__ = "Cleiton Pinheiro a.k.a MrCl0wn"
__git_project__ = 'https://github.com/osintbrazuca'
__license__ = "MIT"
