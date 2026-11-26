import sys

from bundle.window import main

if __name__ == "__main__":
    if sys.argv[1:] == ["--reader-self-test"]:
        from bundle.health import self_test

        sys.exit(self_test())
    else:
        main()
