def pytest_addoption(parser):
    parser.addoption(
        "--matchmaking-url",
        default="https://bomberman.romanellas.cloud/matchmaking",
        help="Matchmaking endpoint URL",
    )
    parser.addoption(
        "--deploy-timeout",
        type=int,
        default=360,
        help="Seconds to wait for deployment readiness",
    )