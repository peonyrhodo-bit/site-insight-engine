from director.trace_context import correlation_id_var, get_correlation_id


def test_correlation_id_context_can_be_set_and_reset():
    token = correlation_id_var.set("audit-run-17")
    try:
        assert get_correlation_id() == "audit-run-17"
    finally:
        correlation_id_var.reset(token)
