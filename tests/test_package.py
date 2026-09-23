"""Test that the sonar package imports correctly."""


def test_import_sonar():
    """Test that sonar can be imported and has correct __name__."""
    import sonar

    assert sonar.__name__ == "sonar"
