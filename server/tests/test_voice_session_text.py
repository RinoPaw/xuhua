from heritage_explorer.voice_session import contains_spoken_text


def test_punctuation_only_partial_is_not_spoken_text():
    assert contains_spoken_text("……！？") is False
    assert contains_spoken_text("   ") is False


def test_letters_digits_and_chinese_are_spoken_text():
    assert contains_spoken_text("hello") is True
    assert contains_spoken_text("123") is True
    assert contains_spoken_text("汴绣") is True
