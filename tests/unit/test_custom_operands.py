"""Unit tests for custom operand system: registry, parser transformation, executor."""

import copy
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import sys
import textwrap

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.scenarios.operand_registry import OperandRegistry, OperandDefinition
from src.scenarios.schema_operand import CustomOperandStep
from src.scenarios.schema import TestScenario, CLIStep, TestStep, CustomOperandStep as SchemaCustomOperandStep
from src.scenarios.parser import BaseScenarioParser, ScenarioParser
from src.scenarios.executor import RuntimeContext, ScenarioExecutionError


# ---------------------------------------------------------------------------
# OperandRegistry
# ---------------------------------------------------------------------------

class TestOperandRegistry:

    def test_empty_registry(self):
        reg = OperandRegistry()
        assert reg.names == set()
        assert not reg.is_operand("kelvpn")

    def test_load_from_directory(self, tmp_path):
        op_file = tmp_path / "myop.yml"
        op_file.write_text(textwrap.dedent("""\
            operand: myop
            description: "Test operand"
            actions:
              hello:
                steps:
                  - print: "hello from {{name}}"
              bye:
                steps:
                  - print: "bye"
        """))

        reg = OperandRegistry()
        reg.load_directory(tmp_path)

        assert reg.names == {"myop"}
        assert reg.is_operand("myop")
        assert not reg.is_operand("other")

        defn = reg.get("myop")
        assert defn.name == "myop"
        assert defn.description == "Test operand"
        assert set(defn.actions.keys()) == {"hello", "bye"}

    def test_get_action_steps(self, tmp_path):
        op_file = tmp_path / "op.yml"
        op_file.write_text(textwrap.dedent("""\
            operand: op
            actions:
              do_it:
                steps:
                  - print: "step1"
                  - print: "step2"
        """))

        reg = OperandRegistry()
        reg.load_directory(tmp_path)

        steps = reg.get("op").get_action_steps("do_it")
        assert len(steps) == 2
        assert steps[0] == {"print": "step1"}

    def test_get_action_steps_unknown_action(self, tmp_path):
        op_file = tmp_path / "op.yml"
        op_file.write_text(textwrap.dedent("""\
            operand: op
            actions:
              existing:
                steps:
                  - print: "ok"
        """))

        reg = OperandRegistry()
        reg.load_directory(tmp_path)

        with pytest.raises(KeyError, match="no action 'missing'"):
            reg.get("op").get_action_steps("missing")

    def test_non_operand_yaml_ignored(self, tmp_path):
        (tmp_path / "not_op.yml").write_text("name: regular scenario\n")
        reg = OperandRegistry()
        reg.load_directory(tmp_path)
        assert reg.names == set()

    def test_missing_directory(self, tmp_path):
        reg = OperandRegistry()
        reg.load_directory(tmp_path / "nonexistent")
        assert reg.names == set()

    def test_returns_new_list_per_call(self, tmp_path):
        """Each call returns a new list object (shallow copy)."""
        op_file = tmp_path / "op.yml"
        op_file.write_text(textwrap.dedent("""\
            operand: op
            actions:
              act:
                steps:
                  - print: "original"
        """))
        reg = OperandRegistry()
        reg.load_directory(tmp_path)

        steps1 = reg.get("op").get_action_steps("act")
        steps2 = reg.get("op").get_action_steps("act")
        assert steps1 is not steps2
        assert steps1 == steps2

    def test_multiple_operands(self, tmp_path):
        """Multiple operand files in same directory."""
        (tmp_path / "alpha.yml").write_text(textwrap.dedent("""\
            operand: alpha
            actions:
              go:
                steps:
                  - print: "alpha"
        """))
        (tmp_path / "beta.yml").write_text(textwrap.dedent("""\
            operand: beta
            actions:
              go:
                steps:
                  - print: "beta"
        """))
        reg = OperandRegistry()
        reg.load_directory(tmp_path)
        assert reg.names == {"alpha", "beta"}


# ---------------------------------------------------------------------------
# CustomOperandStep schema
# ---------------------------------------------------------------------------

class TestCustomOperandStepSchema:

    def test_basic_creation(self):
        step = CustomOperandStep(
            operand_name="kelvpn",
            operand_action="install",
            operand_params={"nodes": ["n7"]},
        )
        assert step.operand_name == "kelvpn"
        assert step.operand_action == "install"
        assert step.operand_params == {"nodes": ["n7"]}
        assert step.description is None

    def test_with_description(self):
        step = CustomOperandStep(
            operand_name="kelvpn",
            operand_action="cli",
            operand_params={"args": "--version"},
            description="check version",
        )
        assert step.description == "check version"

    def test_empty_params(self):
        step = CustomOperandStep(
            operand_name="op",
            operand_action="act",
        )
        assert step.operand_params == {}

    def test_in_test_step_union(self):
        """CustomOperandStep should be parseable as TestStep."""
        from pydantic import TypeAdapter
        adapter = TypeAdapter(TestStep)
        parsed = adapter.validate_python({
            "operand_name": "kelvpn",
            "operand_action": "install",
            "operand_params": {"nodes": ["n7"]},
        })
        assert isinstance(parsed, CustomOperandStep)


# ---------------------------------------------------------------------------
# Parser: operand step transformation
# ---------------------------------------------------------------------------

class TestParserOperandTransformation:

    def _make_parser(self, tmp_path):
        """Create parser with a test operand registered."""
        operands_dir = tmp_path / "common" / "operands"
        operands_dir.mkdir(parents=True)
        (operands_dir / "testop.yml").write_text(textwrap.dedent("""\
            operand: testop
            actions:
              run:
                steps:
                  - print: "running with {{x}}"
        """))
        return BaseScenarioParser(scenarios_root=tmp_path, common_root=tmp_path)

    def test_simple_step_transformed(self, tmp_path):
        parser = self._make_parser(tmp_path)
        data = {"testop": "run", "x": 42}
        result = parser._transform_operand_steps(data)
        assert result == {
            "operand_name": "testop",
            "operand_action": "run",
            "operand_params": {"x": 42},
            "description": None,
        }

    def test_description_preserved(self, tmp_path):
        parser = self._make_parser(tmp_path)
        data = {"testop": "run", "x": 1, "description": "do stuff"}
        result = parser._transform_operand_steps(data)
        assert result["description"] == "do stuff"
        assert "description" not in result["operand_params"]

    def test_non_operand_step_unchanged(self, tmp_path):
        parser = self._make_parser(tmp_path)
        data = {"print": "hello"}
        result = parser._transform_operand_steps(data)
        assert result == {"print": "hello"}

    def test_nested_in_if_else(self, tmp_path):
        parser = self._make_parser(tmp_path)
        data = {
            "setup": [
                {"if": "flag",
                 "then": [{"print": "yes"}],
                 "else": [
                     {"testop": "run", "x": 99},
                     {"print": "after"},
                 ]}
            ]
        }
        result = parser._transform_operand_steps(data)
        else_steps = result["setup"][0]["else"]
        assert else_steps[0]["operand_name"] == "testop"
        assert else_steps[0]["operand_params"] == {"x": 99}
        assert else_steps[1] == {"print": "after"}

    def test_nested_in_for_loop(self, tmp_path):
        parser = self._make_parser(tmp_path)
        data = {
            "steps": [
                {"for": "item",
                 "in": [1, 2],
                 "steps": [
                     {"testop": "run", "x": "{{item}}"},
                 ]}
            ]
        }
        result = parser._transform_operand_steps(data)
        inner = result["steps"][0]["steps"][0]
        assert inner["operand_name"] == "testop"

    def test_known_step_keys_not_transformed(self, tmp_path):
        """Step keys like 'set', 'cli' must NOT collide with operand names."""
        parser = self._make_parser(tmp_path)
        data = {"set": "my_var", "value": 123}
        result = parser._transform_operand_steps(data)
        assert result == {"set": "my_var", "value": 123}

    def test_no_operands_noop(self, tmp_path):
        parser = BaseScenarioParser(scenarios_root=tmp_path)
        data = {"testop": "run", "x": 1}
        result = parser._transform_operand_steps(data)
        assert result == data

    def test_full_scenario_parse(self, tmp_path):
        """Test that a full scenario with custom operand parses via Pydantic."""
        operands_dir = tmp_path / "common" / "operands"
        operands_dir.mkdir(parents=True)
        (operands_dir / "testop.yml").write_text(textwrap.dedent("""\
            operand: testop
            actions:
              run:
                steps:
                  - print: "running with {{x}}"
        """))
        scenario_file = tmp_path / "scenario.yml"
        scenario_file.write_text(textwrap.dedent("""\
            name: Operand Test
            description: Tests custom operand parsing
            setup:
              - testop: run
                x: hello
            test:
              - cli: version
                node: node1
        """))
        sp = ScenarioParser(scenarios_root=tmp_path, common_root=tmp_path)
        scenario = sp.load_scenario("scenario.yml")

        assert scenario.name == "Operand Test"
        assert len(scenario.setup.steps) == 1
        step0 = scenario.setup.steps[0]
        assert isinstance(step0, CustomOperandStep)
        assert step0.operand_name == "testop"
        assert step0.operand_action == "run"
        assert step0.operand_params == {"x": "hello"}


# ---------------------------------------------------------------------------
# CustomOperandStepExecutor
# ---------------------------------------------------------------------------

class TestCustomOperandExecutor:

    @pytest.fixture
    def registry(self, tmp_path):
        op_file = tmp_path / "greet.yml"
        op_file.write_text(textwrap.dedent("""\
            operand: greet
            actions:
              say:
                steps:
                  - print: "Hello {{who}}"
        """))
        reg = OperandRegistry()
        reg.load_directory(tmp_path)
        return reg

    @pytest.fixture
    def ctx(self):
        scenario = TestScenario(
            name="test", description="test",
            test=[CLIStep(cli="version")],
        )
        return RuntimeContext(scenario)

    @pytest.mark.asyncio
    async def test_execute_basic(self, registry, ctx):
        executed_steps = []

        async def mock_execute_steps(steps, ctx, defaults=None):
            for s in steps:
                executed_steps.append(s)

        from src.scenarios.step.custom_operand import CustomOperandStepExecutor
        executor = CustomOperandStepExecutor(
            container_manager=None, log_file=None, debug=False,
            registry=registry,
            execute_steps_callback=mock_execute_steps,
        )

        step = CustomOperandStep(
            operand_name="greet",
            operand_action="say",
            operand_params={"who": "world"},
        )
        await executor.execute(step, ctx)

        assert len(executed_steps) == 1
        from src.scenarios.schema import PrintStep
        assert isinstance(executed_steps[0], PrintStep)

    @pytest.mark.asyncio
    async def test_params_injected_and_restored(self, registry, ctx):
        ctx.set_variable("who", "ORIGINAL")

        async def mock_execute_steps(steps, ctx, defaults=None):
            assert ctx.get_variable("who") == "world"

        from src.scenarios.step.custom_operand import CustomOperandStepExecutor
        executor = CustomOperandStepExecutor(
            container_manager=None, log_file=None, debug=False,
            registry=registry,
            execute_steps_callback=mock_execute_steps,
        )

        step = CustomOperandStep(
            operand_name="greet",
            operand_action="say",
            operand_params={"who": "world"},
        )
        await executor.execute(step, ctx)

        assert ctx.get_variable("who") == "ORIGINAL"

    @pytest.mark.asyncio
    async def test_new_params_cleaned_up(self, registry, ctx):
        assert not ctx.has_variable("who")

        async def mock_execute_steps(steps, ctx, defaults=None):
            assert ctx.get_variable("who") == "test"

        from src.scenarios.step.custom_operand import CustomOperandStepExecutor
        executor = CustomOperandStepExecutor(
            container_manager=None, log_file=None, debug=False,
            registry=registry,
            execute_steps_callback=mock_execute_steps,
        )

        step = CustomOperandStep(
            operand_name="greet",
            operand_action="say",
            operand_params={"who": "test"},
        )
        await executor.execute(step, ctx)

        assert not ctx.has_variable("who")

    @pytest.mark.asyncio
    async def test_unknown_operand_raises(self, registry, ctx):
        from src.scenarios.step.custom_operand import CustomOperandStepExecutor
        executor = CustomOperandStepExecutor(
            container_manager=None, log_file=None, debug=False,
            registry=registry,
            execute_steps_callback=AsyncMock(),
        )

        step = CustomOperandStep(
            operand_name="nonexistent",
            operand_action="do",
        )
        with pytest.raises(ScenarioExecutionError, match="Unknown custom operand"):
            await executor.execute(step, ctx)

    @pytest.mark.asyncio
    async def test_unknown_action_raises(self, registry, ctx):
        from src.scenarios.step.custom_operand import CustomOperandStepExecutor
        executor = CustomOperandStepExecutor(
            container_manager=None, log_file=None, debug=False,
            registry=registry,
            execute_steps_callback=AsyncMock(),
        )

        step = CustomOperandStep(
            operand_name="greet",
            operand_action="nonexistent",
        )
        with pytest.raises(KeyError, match="no action 'nonexistent'"):
            await executor.execute(step, ctx)

    @pytest.mark.asyncio
    async def test_variable_substitution_in_params(self, registry, ctx):
        ctx.set_variable("target", "Mars")

        async def mock_execute_steps(steps, ctx, defaults=None):
            assert ctx.get_variable("who") == "Mars"

        from src.scenarios.step.custom_operand import CustomOperandStepExecutor
        executor = CustomOperandStepExecutor(
            container_manager=None, log_file=None, debug=False,
            registry=registry,
            execute_steps_callback=mock_execute_steps,
        )

        step = CustomOperandStep(
            operand_name="greet",
            operand_action="say",
            operand_params={"who": "{{target}}"},
        )
        await executor.execute(step, ctx)


# ---------------------------------------------------------------------------
# Integration: kelvpn operand loading
# ---------------------------------------------------------------------------

class TestKelvpnOperandLoading:
    """Verify the real kelvpn.yml operand loads correctly."""

    @pytest.fixture
    def kelvpn_registry(self):
        kelvpn_dir = Path(__file__).parent.parent.parent.parent.parent / "tests" / "e2e" / "common" / "operands"
        if not kelvpn_dir.exists():
            pytest.skip("kelvpn operand YAML not found")
        reg = OperandRegistry()
        reg.load_directory(kelvpn_dir)
        return reg

    def test_kelvpn_registered(self, kelvpn_registry):
        assert kelvpn_registry.is_operand("kelvpn")

    def test_kelvpn_actions(self, kelvpn_registry):
        defn = kelvpn_registry.get("kelvpn")
        assert {"install", "set", "cli"} <= set(defn.actions.keys())

    def test_kelvpn_install_has_steps(self, kelvpn_registry):
        steps = kelvpn_registry.get("kelvpn").get_action_steps("install")
        assert len(steps) >= 4

    def test_kelvpn_cli_has_steps(self, kelvpn_registry):
        steps = kelvpn_registry.get("kelvpn").get_action_steps("cli")
        assert len(steps) >= 1
