    """
    Application-wide runtime dependencies.
    """

    def __init__(self) -> None:
        self.memory = ServerMemory()
        self.analytics = AnalyticsAdapter()
        self.data = DataAdapter(
            storage=self.memory.backend,
        )
        self.ai = AIAdapter()
