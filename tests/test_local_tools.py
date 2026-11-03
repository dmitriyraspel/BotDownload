from bot.local_tools import yt_dlp_js_options


def test_deno_configuration_is_optional():
    options = yt_dlp_js_options()
    assert options == {} or (
        "deno" in options["js_runtimes"]
        and options["js_runtimes"]["deno"]["path"]
    )
