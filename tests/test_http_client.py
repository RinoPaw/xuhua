"""Tests for http_client: singleton, error wrapping, API key sanitization."""
import pytest
import httpx
from heritage_explorer.http_client import (
    get_http_client,
    describe_error,
)


def test_get_http_client_returns_same_instance():
    c1 = get_http_client()
    c2 = get_http_client()
    assert c1 is c2


def test_describe_error_http_status():
    request_obj = httpx.Request("POST", "http://test.example/api")
    response = httpx.Response(500, content=b"Internal Server Error", request=request_obj)
    exc = httpx.HTTPStatusError("fail", request=request_obj, response=response)
    desc = describe_error(exc)
    assert "500" in desc


def test_describe_error_strips_api_key():
    exc = httpx.RequestError("Failed with key api-key-secret-12345")
    desc = describe_error(exc, api_key="api-key-secret-12345")
    assert "api-key-secret-12345" not in desc
    assert "***" in desc


def test_describe_error_handles_generic_exception():
    exc = ValueError("something broke")
    desc = describe_error(exc)
    assert "something broke" in desc
