from __future__ import annotations

from .bootstrap import seed
from .config import Settings
from .evidence import EvidenceStore
from .evolution import Evaluator, Evolution
from .knowledge import Knowledge
from .memory import Memory
from .learning import LearningCycle
from .providers import ModelGateway
from .runtime import Runtime
from .store import Store
from .tools import ToolBus
from .writeup import Writeup


class Components:
    def __init__(self, settings: Settings, provider=None):
        self.settings = settings
        self.store = Store(settings.data_dir)
        self.evidence = EvidenceStore(self.store, settings.max_output_bytes)
        self.knowledge = Knowledge(self.store, settings)
        self.memory = Memory(self.store, self.evidence, self.knowledge)
        self.writeup = Writeup(self.store, self.evidence)
        self.evolution = Evolution(self.store)
        seed(self.knowledge, self.evolution)
        self.gateway = ModelGateway(self.store, settings, provider)
        self.tools = ToolBus(self.store, settings, self.evidence, self.knowledge)
        from .run_sandbox import RunSandboxes
        self.sandboxes = RunSandboxes(self.store, settings)
        self.tools.sandbox = self.sandboxes
        from .investigation import Investigation
        self.investigation = Investigation(self)
        self.tools.investigation = self.investigation
        from .browser import Browsers
        from .terminal import Terminals
        self.browsers, self.terminals = Browsers(self), Terminals(self)
        self.tools.browsers = self.browsers
        from .platforms import Platforms
        self.platforms = Platforms(self)
        from .scopesentry import ScopeSentry
        self.scopesentry = ScopeSentry(self)
        self.runtime = Runtime(self.store, settings, self.gateway, self.tools, self.memory, self.knowledge)
        from .engines import Engines
        self.engines = Engines(self)
        self.runtime.engines = self.engines
        self.evaluator = Evaluator(self.store, self.runtime)
        self.learning = LearningCycle(self)
        from .extensions import Extensions
        self.extensions = Extensions(self)
        self.tools.extensions = self.extensions
        from .competition import Competitions
        self.competitions = Competitions(self)

