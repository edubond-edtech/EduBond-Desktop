import pytest

from edukit.comms import protocol as P


def test_encode_is_single_ndjson_line():
    data = P.encode({"command": "ping", "id": 1})
    assert data.endswith(b"\n") and data.count(b"\n") == 1


def test_encode_rejects_oversized():
    with pytest.raises(P.ProtocolError):
        P.encode({"x": "a" * 2000})


def test_decoder_handles_partial_reads_and_noise():
    d = P.LineDecoder()
    assert d.feed(b'ets Jun  8 2016 rst:0x1\r\n{"type":"hel') == [P.Noise("ets Jun  8 2016 rst:0x1")]
    out = d.feed(b'lo","device_id":"X","role":"input"}\n{"type":"ack","id":3}\n')
    assert out == [{"type": "hello", "device_id": "X", "role": "input"}, {"type": "ack", "id": 3}]


def test_decoder_bad_json_is_noise():
    d = P.LineDecoder()
    (item,) = d.feed(b"{not json}\n")
    assert isinstance(item, P.Noise)


def test_decoder_overflow_discards_line_and_recovers():
    d = P.LineDecoder(max_line=64)
    out = d.feed(b"{" + b"a" * 100)
    assert isinstance(out[0], P.Noise)
    out = d.feed(b'aaa}\n{"type":"ack","id":1}\n')
    assert out == [{"type": "ack", "id": 1}]


@pytest.mark.parametrize(
    "msg",
    [
        {"type": "nope"},
        {"type": "hello", "role": "input"},
        {"type": "hello", "device_id": "X", "role": "toaster"},
        {"type": "event", "event": "answer_selected"},
        {"type": "ack"},
        ["not", "a", "dict"],
    ],
)
def test_validate_rejects(msg):
    with pytest.raises(P.ProtocolError):
        P.validate_inbound(msg)


def test_validate_accepts_spec_example():
    msg = {"type": "event", "device_id": "INPUT_01", "seq": 1, "event": "answer_selected", "question_id": "Q001", "selected_answer": "C"}
    assert P.validate_inbound(msg) is msg
