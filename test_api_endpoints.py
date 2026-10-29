"""Read-only market contract verification; importing this module performs no I/O.

python test_api_endpoints.py                # offline checks + configured live provider
python test_api_endpoints.py --broker both  # verify Kite and Breeze
python test_api_endpoints.py --offline      # fixtures and request headers only
"""

from tools.verify_market_data import main


if __name__ == "__main__":
    raise SystemExit(main())
