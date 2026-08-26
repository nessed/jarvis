import logging

from bus.logging import RedactVerifyTokenFilter, redact_verify_token_from_access_log


def test_filter_redacts_verify_token_from_uvicorn_style_access_log_args(caplog) -> None:
    logger = logging.getLogger("test.uvicorn.access")
    logger.addFilter(RedactVerifyTokenFilter())

    with caplog.at_level(logging.INFO, logger="test.uvicorn.access"):
        logger.info(
            '%s - "%s %s HTTP/%s" %d',
            "127.0.0.1:54321",
            "GET",
            "/webhook?hub.mode=subscribe&hub.verify_token=super-secret-value&hub.challenge=123",
            "1.1",
            200,
        )

    message = caplog.records[0].getMessage()
    assert "super-secret-value" not in message
    assert "hub.verify_token=REDACTED" in message
    assert "hub.challenge=123" in message
    assert "GET" in message and "200" in message


def test_filter_leaves_requests_without_a_verify_token_untouched(caplog) -> None:
    logger = logging.getLogger("test.uvicorn.access.clean")
    logger.addFilter(RedactVerifyTokenFilter())

    with caplog.at_level(logging.INFO, logger="test.uvicorn.access.clean"):
        logger.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:1", "POST", "/webhook", "1.1", 200)

    assert caplog.records[0].getMessage() == '127.0.0.1:1 - "POST /webhook HTTP/1.1" 200'


def test_redact_verify_token_from_access_log_attaches_filter_once() -> None:
    logger_name = "test.uvicorn.access.idempotent"
    logger = logging.getLogger(logger_name)
    logger.filters.clear()

    redact_verify_token_from_access_log(logger_name)
    redact_verify_token_from_access_log(logger_name)

    assert sum(isinstance(f, RedactVerifyTokenFilter) for f in logger.filters) == 1
