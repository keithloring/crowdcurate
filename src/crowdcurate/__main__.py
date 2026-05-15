try:
    from .app import main
except ImportError:
    import sys
    from pathlib import Path

    package_root = Path(__file__).resolve().parents[1]
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))
    from crowdcurate.app import main

if __name__ == "__main__":
    raise SystemExit(main())
