from aircue.app.cli import build_parser


def test_cli_parser_is_available() -> None:
    assert build_parser().prog == "aircue"
