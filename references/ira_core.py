root@304a81248b87:/workspace/grad-project# ls -R /isaac-sim/extscache/isaacsim.replicator.agent.core-0.7.28+107.3.3/isaacsim 2>/dev/null
/isaac-sim/extscache/isaacsim.replicator.agent.core-0.7.28+107.3.3/isaacsim:
replicator

/isaac-sim/extscache/isaacsim.replicator.agent.core-0.7.28+107.3.3/isaacsim/replicator:
agent

/isaac-sim/extscache/isaacsim.replicator.agent.core-0.7.28+107.3.3/isaacsim/replicator/agent:
core

/isaac-sim/extscache/isaacsim.replicator.agent.core-0.7.28+107.3.3/isaacsim/replicator/agent/core:
__init__.py  agent_manager.py  data_generation  incident_bridge.py  response     simulation.py  tests
__pycache__  config_file       extension.py     randomization       settings.py  stage_util.py

/isaac-sim/extscache/isaacsim.replicator.agent.core-0.7.28+107.3.3/isaacsim/replicator/agent/core/__pycache__:
__init__.cpython-311.pyc       extension.cpython-311.pyc  stage_util.cpython-311.pyc
agent_manager.cpython-311.pyc  settings.cpython-311.pyc

/isaac-sim/extscache/isaacsim.replicator.agent.core-0.7.28+107.3.3/isaacsim/replicator/agent/core/config_file:
__init__.py  __pycache__  default.py  defines.py

/isaac-sim/extscache/isaacsim.replicator.agent.core-0.7.28+107.3.3/isaacsim/replicator/agent/core/config_file/__pycache__:
__init__.cpython-311.pyc  default.cpython-311.pyc  defines.cpython-311.pyc

/isaac-sim/extscache/isaacsim.replicator.agent.core-0.7.28+107.3.3/isaacsim/replicator/agent/core/data_generation:
annotator_data_processor.py  data_generation.py  object_info_manager.py  writers

/isaac-sim/extscache/isaacsim.replicator.agent.core-0.7.28+107.3.3/isaacsim/replicator/agent/core/data_generation/writers:
__init__.py  __pycache__  rtsp.py  stereo.py  tao.py  writer.py  writer_utils.py

/isaac-sim/extscache/isaacsim.replicator.agent.core-0.7.28+107.3.3/isaacsim/replicator/agent/core/data_generation/writers/__pycache__:
__init__.cpython-311.pyc

/isaac-sim/extscache/isaacsim.replicator.agent.core-0.7.28+107.3.3/isaacsim/replicator/agent/core/randomization:
__pycache__           carter_randomizer.py     iw_hub_randomizer.py  randomizer_util.py
camera_randomizer.py  character_randomizer.py  randomizer.py         robot_randomizer.py

/isaac-sim/extscache/isaacsim.replicator.agent.core-0.7.28+107.3.3/isaacsim/replicator/agent/core/randomization/__pycache__:
randomizer_util.cpython-311.pyc

/isaac-sim/extscache/isaacsim.replicator.agent.core-0.7.28+107.3.3/isaacsim/replicator/agent/core/response:
core.py

/isaac-sim/extscache/isaacsim.replicator.agent.core-0.7.28+107.3.3/isaacsim/replicator/agent/core/tests:
__init__.py             test_command_injection.py  test_rtsp.py        test_writers.py
test_agent_response.py  test_randomization.py      test_simulation.py
root@304a81248b87:/workspace/grad-project# find /isaac-sim/extscache/isaacsim.replicator.agent.core-0.7.28+107.3.3 \( -name "agent_manager.py" -o -name "stage_util.py" -o -name "settings.py" -o -name "behavior_utils.py" -o -name "character_manager.py" \) -print -exec cat {} \;
/isaac-sim/extscache/isaacsim.replicator.agent.core-0.7.28+107.3.3/isaacsim/replicator/agent/core/agent_manager.py
# Copyright (c) 2022, NVIDIA CORPORATION.  All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto.  Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.

from __future__ import annotations

import carb
import omni.usd
from omni.anim.people.settings import AgentEvent
from pxr import Usd
import OmniScriptingSchema
from omni.metropolis.utils.simulation_util import SimulationUtil
from omni.metropolis.utils.semantics_util import SemanticsUtils
from omni.metropolis.utils.usd_util import USDUtil
from typing import Any, Tuple, Optional, Callable

from .stage_util import CharacterUtil, RobotUtil, StageUtil
from .settings import PrimPaths


class AgentData:
    """
    Class that helps match character_label with primpath and skelroot path,
    allowing for fixed parameters and additional user-defined metadata.
    """

    # define several basic attribute:
    FIXED_ATTRIBUTES = {"label_path", "prim_path"}

    def __init__(
        self,
        label_path: Optional[str] = None,
        prim_path: Optional[str] = None,
        **kwargs,
    ):
        # Dynamically initialize fixed attributes
        for attr in self.FIXED_ATTRIBUTES:
            setattr(self, attr, locals()[attr])  # Set attributes dynamically

        # Metadata for additional attributes
        self.metadata = kwargs

    def __setattr__(self, name, value):
        """Check if the attribute is one of the fixed attributes"""
        if name in self.FIXED_ATTRIBUTES or name == "metadata":
            super().__setattr__(name, value)
        else:
            # Store additional attributes in metadata
            if value is not None:
                self.metadata[name] = value

    def __getattr__(self, name):
        """Allow access to metadata as if they were attributes"""
        return self.metadata.get(name, None)

    def get_metadata(self):
        """get all metadata of agent"""
        return self.metadata


class AgentManager:
    """Global class which stores current and predicted positions of all agents and moving objects."""

    __instance: AgentManager = None

    def __init__(self):
        if self.__instance is not None:
            raise RuntimeError("Only one instance of AgentManager is allowed")

        # This maps agent name with its BehaviorScript instance
        # Agents are register when Simulation starts, and are deregistered when simulation ends
        self._agent_name_to_script_inst = {}

        self._agent_registered_sub = None  # add subscription to agent register event
        self._metadata_updated_sub = None  # add subscription to metadata updated event
        self._stage_closing_event_sub = None
        self._stage_opened_event_sub = None
        self._stage_animation_stop_event_sub = None

        # fetching data for writers:
        # Create 3 dictionaries, allow user to search character in different way
        self.agents_by_label_path: dict[str, AgentData] = {}
        self.agents_by_primpath: dict[str, AgentData] = {}
        self.agents_by_skelpath: dict[str, AgentData] = {}
        # the design to record agent's action tag
        self.agents_by_agentname: dict[str, AgentData] = {}

        AgentManager.__instance = self
        self.register_event_function()

    def register_event_function(self):
        """
        register event functions for when an agent is registered and when its metadata is updated
        clean the registry when the simulation stops
        """
        # subscription to agent register event
        self._agent_registered_sub = carb.eventdispatcher.get_eventdispatcher().observe_event(
            event_name=AgentEvent.AgentRegistered, on_event=self.on_agent_registered,
            observer_name="isaacsim/replicator/agent/ON_AGENT_REGISTERED"
        )
        # subscription to metadata update event
        self._metadata_updated_sub = carb.eventdispatcher.get_eventdispatcher().observe_event(
            event_name=AgentEvent.MetadataUpdateEvent, on_event=self.on_metadata_updated,
            observer_name="isaacsim/replicator/agent/ON_METADATA_UPDATED"
        )

        self._usd_context = omni.usd.get_context()
        if self._usd_context is not None and self._stage_closing_event_sub is None:
            self._stage_closing_event_sub = carb.eventdispatcher.get_eventdispatcher().observe_event(
                event_name=omni.usd.get_context().stage_event_name(omni.usd.StageEventType.CLOSING),
                on_event=self.__on_stage_event,
                observer_name="isaacsim/replicator/agent/CLEAN_REGISTERED_AGENT",
            )
            self._stage_opened_event_sub = carb.eventdispatcher.get_eventdispatcher().observe_event(
                event_name=omni.usd.get_context().stage_event_name(omni.usd.StageEventType.OPENED),
                on_event=self.__on_stage_event,
                observer_name="isaacsim/replicator/agent/CLEAN_REGISTERED_AGENT",
            )
            self._stage_animation_stop_event_sub = carb.eventdispatcher.get_eventdispatcher().observe_event(
                event_name=omni.usd.get_context().stage_event_name(omni.usd.StageEventType.SIMULATION_STOP_PLAY),
                on_event=self.__on_stage_event,
                observer_name="isaacsim/replicator/agent/CLEAN_REGISTERED_AGENT",
            )

    def clean_all_event(self):
        """remove all registered events"""
        self._bus = None
        self._agent_registered_sub = None
        self._metadata_updated_sub = None
        self._stage_closing_event_sub = None
        self._stage_opened_event_sub = None
        self._stage_animation_stop_event_sub = None

    def destroy(self):
        self.clear_agent()
        self.clean_all_event()
        self.clear_agent_data_dicts()

        AgentManager.__instance = None

    def __del__(self):
        self.destroy()

    @classmethod
    def get_instance(cls) -> AgentManager:
        if cls.__instance is None:
            AgentManager()
        return cls.__instance

    @classmethod
    def has_instance(cls) -> bool:
        if cls.__instance is None:
            return False
        return True

    def __on_stage_event(self, event):
        """at the end of simulation or stage is changed, clean all registered agent and agent info"""
        # clean all the registered agent
        self.clear_agent()
        # clean all character_data
        self.clear_agent_data_dicts()

    def clear_agent(self):
        self._agent_name_to_script_inst.clear()

    def on_agent_registered(self, e):
        """ "
        This function would be triggered when agent instance are created.
        It will register the agent to the manager
        """
        agent_info = e.payload
        # check whether agent info has content
        if agent_info is None:
            return
        # check whether agent name is correct
        agent_name = agent_info["agent_name"]
        agent_prim_path = agent_info["prim_path"]
        self.register_agent(agent_name, agent_prim_path)
        carb.log_info(f"{agent_name} is registered with prim path {agent_prim_path}")

    def on_metadata_updated(self, e):
        """ "
        This function would be triggered when agent's metadata are updated.
        It will update the metadata tag in the dictionary
        """
        agent_info = e.payload
        # check whether agent info has content
        if agent_info is None:
            return
        # check whether agent name is correct
        agent_name = agent_info["agent_name"]
        data_name = agent_info["data_name"]
        data_value = agent_info["data_value"]
        self.set_metadata_value(agent_name=agent_name, data_name=data_name, data_value=data_value)

    def register_agent(self, agent_name, agent_prim_path):
        """Register the agent to the manager by creating mapping for agent name to its BehaviorScript instance"""
        # get the BehaviorScript inst
        agent_inst = SimulationUtil.get_agent_script_instance_by_path(agent_prim_path)
        # add the agent inst to the dict
        self._agent_name_to_script_inst[agent_name] = agent_inst

    def agent_registered(self, agent_name) -> bool:
        """Check whether the given agent is registered in the dict"""
        if agent_name not in self._agent_name_to_script_inst.keys():
            carb.log_warn(f"Agent is not registered to Agent Manager: {agent_name}")
            return False
        return True

    def deregister_agent(self, agent_name):
        """Remove the agent from the agent script dict"""
        if self.agent_registered(agent_name):
            self._agent_name_to_script_inst[agent_name] = None

    def get_agent_script_instance_by_name(self, agent_name):
        """Get the agent behavior script by its name"""
        if self.agent_registered(agent_name):
            return self._agent_name_to_script_inst[agent_name]
        return None

    def get_agent_pos_by_name(self, name):
        """Get the agent position by its name"""
        agent = self.get_agent_script_instance_by_name(name)
        if agent:
            return agent.get_current_position()
        else:
            carb.log_error("Agent: {name} does not exist".format(name=name))
            return None

    def get_agent_name_list_with_injected_commands(self, command_list):
        """Get the list of agents that have injected commands"""
        agent_name_list = []
        for command in command_list:
            agent_name_list.append(str(command).strip().split(" ")[0])
        return agent_name_list

    def get_all_agent_names(self):
        """fetch the name of all agents"""
        return self._agent_name_to_script_inst.keys()

    def inject_command_for_all_agents(self, command_list, force_inject):
        """Inject command for all agents"""
        agent_list = self.get_agent_name_list_with_injected_commands(command_list)
        for agent_name, agent_inst in self._agent_name_to_script_inst.items():
            # if agent inst does exist, inject function to the agent
            if str(agent_name) in agent_list and agent_inst is not None:
                self.inject_command(str(agent_name), command_list, force_inject)

    def inject_command(
        self,
        agent_name,
        command_list,
        force_inject=False,
        instant=True,
        on_finished: Tuple[str, Callable[[str, str], None]] = None,
    ):
        """Inject command to target agent"""
        agent_obj = self.get_agent_script_instance_by_name(agent_name)
        if agent_obj is None:
            carb.log_warn(f"Fail to inject command to {agent_name}. Agent is not registered to Agent Manager")
            return

        # force inject will interrupt current command and immediately inject the new commands
        if force_inject and instant:
            agent_obj.end_current_command()
        # inject command to the agent        # TODO:: Find a better way to check if an agent is character or robot
        if str(agent_obj.prim_path).startswith(PrimPaths.characters_parent_path()):
            agent_obj.inject_command(command_list=command_list, executeImmediately=instant, on_finished=on_finished)
        elif str(agent_obj.prim_path).startswith(PrimPaths.robots_parent_path()):
            # RobotBehavior don't have on_finished callback support yet
            agent_obj.inject_command(command_list=command_list, executeImmediately=instant)
        else:
            carb.log_warn(f"Unsupported agent type {type(agent_obj)} during inject command.")

    def replace_command(self, agent_name, command_list, on_finished: Tuple[str, Callable[[str, str], None]] = None):
        """Replace command to target agent"""
        agent_obj = self.get_agent_script_instance_by_name(agent_name)
        if agent_obj is None:
            carb.log_warn(f"Fail to replace command to {agent_name}. Agent is not registered to Agent Manager")
            return

        if str(agent_obj.prim_path).startswith(PrimPaths.characters_parent_path()):
            agent_obj.replace_command(command_list=command_list, on_finished=on_finished)
        else:
            carb.log_warn(f"Unsupported agent type {type(agent_obj)} during replace command.")

    def extract_agent_semantic_prim_path(self, agent_prim: Usd.Prim) -> str:
        """extract target agent semantic info from target prim"""

        # The behavior script always attached on the prim that has transparents updated correctly.
        # Therefore, the semantic lables are usually attached on the same prim path
        for agent_name, agent_script_instance in self._agent_name_to_script_inst.items():
            script_instance_path = str(agent_script_instance.prim_path)
            if script_instance_path.startswith(str(agent_prim.GetPrimPath())):
                return script_instance_path

        # catch the edge case, the agent script instance fail to be registered before the data generation
        for sub_prim in Usd.PrimRange(agent_prim):
            if sub_prim.HasAPI(OmniScriptingSchema.OmniScriptingAPI):
                return str(sub_prim.GetPrimPath())



    def extract_agent_data(self):
        """Store all character semantic label, primpath, and skelpath to dicts"""
        # get current character prim list in the stage
        # refresh the data
        self.clear_agent_data_dicts()
        character_prim_list = CharacterUtil.get_characters_root_in_stage()
        robot_prim_list = RobotUtil.get_robots_in_stage()

        # collect all agent prim in the stage
        agent_prim_list = []
        agent_prim_list.extend(character_prim_list)
        agent_prim_list.extend(robot_prim_list)

        # iterate through agent prim
        for agent_prim in agent_prim_list:
            # extract agent's url path
            agent_name = str(agent_prim.GetName())
            asset_url = USDUtil.get_object_reference(prim=agent_prim)
            # check whether the target prim is a reference object:
            # if so, store the reference url in agent data
            semantic_attach_path = self.extract_agent_semantic_prim_path(agent_prim=agent_prim)
            # extract agent's skeleton path # check whether this agent has skeleton.
            skeleton_path = None
            # iterate all child prims
            for prim_child in Usd.PrimRange(agent_prim):
                # check whether the prim is a skeleton type
                if prim_child.GetTypeName() == "Skeleton":
                    skeleton_prim = prim_child
                    # get agent's skeleton prim path
                    skeleton_path = str(skeleton_prim.GetPrimPath())
            # extract agent's prim path
            agent_prim_path = str(agent_prim.GetPrimPath())
            agent_data = AgentData(
                label_path=semantic_attach_path,
                prim_path=agent_prim_path,
                skelpath=skeleton_path,
                asset_url=asset_url,
            )
            # register the agent data structure in three dictionary.
            self.agents_by_label_path[semantic_attach_path] = agent_data
            self.agents_by_primpath[agent_prim_path] = agent_data
            self.agents_by_agentname[agent_name] = agent_data
            # match the agent with skeleton path
            if skeleton_path is not None:
                self.agents_by_skelpath[skeleton_path] = agent_data

    ## different way to query agent status.
    def get_agent_data_by_prim_path(self, prim_path: str) -> AgentData | None:
        # get agent status via prim path
        return self.agents_by_primpath.get(prim_path)

    # This method need agents to have unique semantic tag/label
    def get_agent_data_by_label_path(self, label_path: str) -> AgentData | None:
        """get agents status via label"""
        return self.agents_by_label_path.get(label_path, None)

    def get_agent_data_by_skelpath(self, skelpath: str) -> AgentData | None:
        """get agents status via skelpath"""
        return self.agents_by_skelpath.get(skelpath, None)

    def is_agent_semantic_prim_path(self, semantic_prim_path: str) -> bool:
        """check whether certain prim path point to a agent"""
        return semantic_prim_path in self.agents_by_label_path

    def clear_agent_data_dicts(self):
        """clean all data stored in agent data dicts"""
        self.agents_by_label_path.clear()
        self.agents_by_primpath.clear()
        self.agents_by_primpath.clear()
        self.agents_by_agentname.clear()

    def set_metadata_value(self, agent_name: str, data_name: str, data_value: Any):
        """set agent's metadata"""
        # check whether agent's metadata exist
        agent_metadata = self.get_agent_metadata_dict(agent_name=agent_name)

        if agent_metadata is None:
            carb.log_warn(
                f"Failed to add {data_name}:{str(data_value)} to agent metadata: "
                f"{agent_name} is not a valid character name"
            )
            return

        agent_metadata[data_name] = data_value

    def get_agent_metadata_dict(self, agent_name):
        """return the agent metadata dict"""
        if agent_name not in self._agent_name_to_script_inst.keys():
            carb.log_info(f"Warning: Failed to feature target agent '{agent_name}' in Info.")
            return None

        agent_data = self.agents_by_agentname.get(agent_name, None)
        if agent_data is None:
            return None

        return agent_data.get_metadata()

    def get_metadata_value(self, agent_name: str, data_name: str) -> str | None:
        """get agent's metadata value"""
        agent_metadata_dict = self.get_agent_metadata_dict(agent_name=agent_name)
        if agent_metadata_dict is None:
            return None

        return agent_metadata_dict.get(data_name, None)

    def get_agent_position(self, agent_name):
        """get agent's location in the stage, no matter whether simulation has been started"""
        if agent_name not in self._agent_name_to_script_inst.keys():
            carb.log_info(" Warning as message :: agent is not registered in the omni.anim.people ")
            # fetch agent name from the stage directly
            character_prim_list = CharacterUtil.get_characters_root_in_stage()
            for character_prim in character_prim_list:
                if character_prim.GetName() == agent_name:
                    character_position = CharacterUtil.get_character_pos(character_prim)
                    return character_position

            return None

        return self.get_agent_pos_by_name(agent_name)
/isaac-sim/extscache/isaacsim.replicator.agent.core-0.7.28+107.3.3/isaacsim/replicator/agent/core/settings.py
"""
    Setting will first read from Carb setting if it is not empty.
    Otherwise it will use default value or fallback value and update it to Carb.
    This way Carb setting is always the actual value in use.
"""

import asyncio
from pathlib import Path
import carb
import carb.settings
import omni.kit
from isaacsim.storage.native.nucleus import get_assets_root_path_async
from omni.metropolis.utils.isaac_sim_util import get_isaac_sim_asset_root_path
from omni.metropolis.utils.carb_util import CarbSettingUtil
from dataclasses import dataclass
from typing import Optional, List, ClassVar, Union


class Settings:
    """
    Manager class to handle general settings
    """

    EXTEND_DATA_GENERATION_LENGTH: ClassVar[str] = (
        "/exts/isaacsim.replicator.agent/extend_data_generation_length"
    )
    SKIP_BIPED_SETUP: ClassVar[str] = "/exts/isaacsim.replicator.agent/skip_biped_setup"
    DEBUG_PRINT: ClassVar[str] = "/exts/isaacsim.replicator.agent/debug_print"

    @classmethod
    def extend_data_generation_length(cls) -> int:
        return CarbSettingUtil.get_value_by_key(
            key=cls.EXTEND_DATA_GENERATION_LENGTH, fallback_value=0, override_setting=True
        )

    @classmethod
    def skip_biped_setup(cls) -> bool:
        return CarbSettingUtil.get_value_by_key(
            key=cls.SKIP_BIPED_SETUP, fallback_value=False, override_setting=True
        )

    @classmethod
    def debug_print(cls) -> bool:
        return CarbSettingUtil.get_value_by_key(
            key=cls.DEBUG_PRINT, fallback_value=False, override_setting=True
        )


class Infos:
    """
    Information that to be shared across the extension
    """

    ext_version = ""
    ext_path = ""


class GlobalValues:
    config_file_format = None


class AssetPaths:
    """
    Manager class to handle all asset paths
    """

    cached_isaac_sim_asset_root_path = None
    USE_ISAAC_SIM_ASSET_ROOT_SETTING = (
        "/exts/isaacsim.replicator.agent/asset_settings/use_isaac_sim_asset_root"
    )
    EXCLUSIVE_CHARACTER_FOLDERS = (
        "/exts/isaacsim.replicator.agent/asset_settings/exclusive_character_assets_folders"
    )

    DEFAULT_BIPED_ASSET_PATH = (
        "/exts/isaacsim.replicator.agent/asset_settings/default_biped_assets_path"
    )
    DEFAULT_SCENE_PATH = (
        "/exts/isaacsim.replicator.agent/asset_settings/default_scene_path"
    )
    DEFAULT_CHARACTER_PATH = (
        "/exts/isaacsim.replicator.agent/asset_settings/default_character_asset_path"
    )

    FALLBACK_BIPED_ASSET_PATH = (
        "/exts/isaacsim.replicator.agent/asset_settings/fallback_biped_assets_path"
    )
    FALLBACK_SCENE_PATH = (
        "/exts/isaacsim.replicator.agent/asset_settings/fallback_scene_path"
    )
    FALLBACK_CHARACTER_PATH = (
        "/exts/isaacsim.replicator.agent/asset_settings/fallback_character_asset_path"
    )

    @classmethod
    def cache_isaac_sim_asset_root_path(cls) -> Optional[str]:
        """Cache the Isaac Sim asset root path for future use."""
        if cls.cached_isaac_sim_asset_root_path is None:
            cls.cached_isaac_sim_asset_root_path = get_isaac_sim_asset_root_path()
        return cls.cached_isaac_sim_asset_root_path


    @classmethod
    def exclusive_character_folders(cls) -> List[str]:
        return CarbSettingUtil.get_value_by_key(
            key=cls.EXCLUSIVE_CHARACTER_FOLDERS, fallback_value=["biped_demo"], override_setting=True
        )

    @classmethod
    def default_biped_asset_path(cls) -> Optional[str]:
        fallback_path = CarbSettingUtil.get_value_by_key(key=cls.FALLBACK_BIPED_ASSET_PATH)
        return cls._get_asset_carb_value(
            cls.DEFAULT_BIPED_ASSET_PATH,
            "/Isaac/People/Characters/Biped_Setup.usd",
            fallback_path,
        )

    @classmethod
    def default_biped_asset_name(cls) -> Optional[str]:
        full_path = cls.default_biped_asset_path()
        if not full_path:
            return None
        return Path(full_path).stem

    @classmethod
    def default_scene_path(cls) -> Optional[str]:
        fallback_path = CarbSettingUtil.get_value_by_key(key=cls.FALLBACK_SCENE_PATH)
        return cls._get_asset_carb_value(
            cls.DEFAULT_SCENE_PATH,
            "/Isaac/Environments/Simple_Warehouse/full_warehouse.usd",
            fallback_path,
        )

    @classmethod
    def default_character_path(cls) -> Optional[str]:
        fallback_path = CarbSettingUtil.get_value_by_key(key=cls.FALLBACK_CHARACTER_PATH)
        return cls._get_asset_carb_value(
            cls.DEFAULT_CHARACTER_PATH, "/Isaac/People/Characters/", fallback_path
        )

    @classmethod
    def _get_asset_carb_value(
        cls,
        carb_setting_key: str,
        default_path_from_root: str,
        fallback_path: Optional[str],
    ) -> Optional[str]:
        """Get asset path from carb settings with fallback logic.

        Args:
            carb_setting_key: The carb settings key to check
            default_path_from_root: Default path relative to Isaac Sim asset root
            fallback_path: Fallback path if other methods fail

        Returns:
            The resolved asset path or None if all methods fail
        """
        # First try the path in carb settings
        path = CarbSettingUtil.get_value_by_key(key=carb_setting_key)
        if path and path.strip():  # Check for non-empty strings
            return path

        # Then try Isaac Sim root assets path (and update to carb)
        # Ensure the cache is populated
        root_path = cls.cached_isaac_sim_asset_root_path
        if root_path and root_path.strip():
            path = root_path + default_path_from_root
            CarbSettingUtil.set_value_by_key(key=carb_setting_key, new_value=path)
            return path

        # Finally we will use fallback path (and update to carb)
        if fallback_path and fallback_path.strip():
            CarbSettingUtil.set_value_by_key(key=carb_setting_key, new_value=fallback_path)
            return fallback_path

        # Log warning if no path could be resolved
        carb.log_warn(f"Could not resolve asset path for key: {carb_setting_key}")
        return None


class BehaviorScriptPaths:
    DEFAULT_BEHAVIOR_SCRIPT_PATH = (
        "/exts/isaacsim.replicator.agent/behavior_script_settings/behavior_script_path"
    )
    DEFAULT_ROBOT_BEHAVIOR_SCRIPT_PATH_PREFIX = (
        "/exts/isaacsim.replicator.agent/behavior_script_settings"
    )

    @classmethod
    def behavior_script_path(cls) -> str:
        fallback_path = (
            omni.kit.app.get_app()
            .get_extension_manager()
            .get_extension_path_by_module("omni.anim.people")
            + "/omni/anim/people/scripts/character_behavior.py"
        )
        return CarbSettingUtil.get_value_by_key(
            key=cls.DEFAULT_BEHAVIOR_SCRIPT_PATH, fallback_value=fallback_path, override_setting=True
        )

    @classmethod
    def robot_behavior_script_path(cls, robot_type: str) -> str:
        fallback_path = (
            omni.kit.app.get_app()
            .get_extension_manager()
            .get_extension_path_by_module("isaacsim.anim.robot")
            + "/isaacsim/anim/robot/agent/"
            + robot_type.lower()
            + ".py"
        )
        carb_key = (
            f"{cls.DEFAULT_ROBOT_BEHAVIOR_SCRIPT_PATH_PREFIX}/{robot_type.lower()}_behavior_script_path"
        )
        return CarbSettingUtil.get_value_by_key(
            key=carb_key, fallback_value=fallback_path, override_setting=True
        )


class PrimPaths:
    """
    Manager class to handle all prim paths
    """

    CHARACTERS_PARENT_PATH = (
        "/exts/isaacsim.replicator.agent/characters_parent_prim_path"
    )
    ROBOTS_PARENT_PATH = (
        "/exts/isaacsim.replicator.agent/robots_parent_prim_path"
    )
    CAMERAS_PARENT_PATH = (
        "/exts/isaacsim.replicator.agent/cameras_parent_prim_path"
    )
    LIDAR_CAMERAS_PARENT_PATH = (
        "/exts/isaacsim.replicator.agent/lidar_cameras_parent_prim_path"
    )

    @classmethod
    def biped_prim_path(cls) -> str:
        biped_name = AssetPaths.default_biped_asset_name()
        return f"{cls.characters_parent_path()}/{biped_name}"

    @classmethod
    def characters_parent_path(cls) -> str:
        return CarbSettingUtil.get_value_by_key(
            key=cls.CHARACTERS_PARENT_PATH, fallback_value="/World/Characters", override_setting=True
        )

    @classmethod
    def robots_parent_path(cls) -> str:
        return CarbSettingUtil.get_value_by_key(
            key=cls.ROBOTS_PARENT_PATH, fallback_value="/World/Robots", override_setting=True
        )

    @classmethod
    def cameras_parent_path(cls) -> str:
        return CarbSettingUtil.get_value_by_key(
            key=cls.CAMERAS_PARENT_PATH, fallback_value="/World/Cameras", override_setting=True
        )

    @classmethod
    def lidar_cameras_parent_path(cls) -> str:
        return CarbSettingUtil.get_value_by_key(
            key=cls.LIDAR_CAMERAS_PARENT_PATH, fallback_value="/World/Lidars", override_setting=True
        )


class WriterSetting:

    DEFAULT_OUTPUT_PATH = (
        "/exts/isaacsim.replicator.agent/default_replicator_output_path"
    )

    class DefaultWriterConstant:
        SHOULDER_OCCLUSION_THRESHOLD = (0.5,)
        WIDTH_THRESHOLD = (0.6,)
        HEIGHT_THRESHOLD = (0.6,)
        SHOULDER_HEIGHT_RATIO = (0.25,)

    class SensorType:
        Lidar = "Lidar"
        Camera = "Camera"
        Unknown = "Unknown"

    class AnnotatorPrefix:
        class ObjectDetection:
            GENERIC = "object_info"
            AGENT_SPECIFIC = "agent_info"

        class Others:
            CUSTOMIZED = "customized"

    class AgentStatus:
        INSIDE = 0
        TRUNCATED = 1
        OUTSIDE = 2

    @classmethod
    def get_writer_default_output_path(cls) -> str:
        fallback_path = str(Path.home().joinpath("ReplicatorResult"))
        return CarbSettingUtil.get_value_by_key(
            key=cls.DEFAULT_OUTPUT_PATH, fallback_value=fallback_path, override_setting=True
        )


class CommandSetting:

    CHARACTER_GOTO_MIN_DISTANCE = (
        "/persistent/exts/isaacsim.replicator.agent/character_goto_min_distance"
    )
    CHARACTER_GOTO_MAX_DISTANCE = (
        "/persistent/exts/isaacsim.replicator.agent/character_goto_max_distance"
    )
    CHARACTER_INTERACT_OBJECT_ROOT_PATH = (
        "/persistent/exts/isaacsim.replicator.agent/character_interact_object_root_path"
    )

    @classmethod
    def get_character_goto_min_distance(cls) -> Optional[float]:
        return CarbSettingUtil.get_value_by_key(
            key=cls.CHARACTER_GOTO_MIN_DISTANCE, fallback_value=None
        )

    @classmethod
    def get_character_goto_max_distance(cls) -> Optional[float]:
        return CarbSettingUtil.get_value_by_key(
            key=cls.CHARACTER_GOTO_MAX_DISTANCE, fallback_value=None
        )

    @classmethod
    def set_character_goto_min_distance(cls, value: float) -> None:
        CarbSettingUtil.set_value_by_key(
            key=cls.CHARACTER_GOTO_MIN_DISTANCE, new_value=value
        )

    @classmethod
    def set_character_goto_max_distance(cls, value: float) -> None:
        CarbSettingUtil.set_value_by_key(
            key=cls.CHARACTER_GOTO_MAX_DISTANCE, new_value=value
        )

    @classmethod
    def get_character_interact_object_root_path(cls) -> Optional[str]:
        return CarbSettingUtil.get_value_by_key(
            key=cls.CHARACTER_INTERACT_OBJECT_ROOT_PATH, fallback_value=None
        )

    @classmethod
    def set_character_interact_object_root_path(cls, value: str) -> None:
        CarbSettingUtil.set_value_by_key(
            key=cls.CHARACTER_INTERACT_OBJECT_ROOT_PATH, new_value=value
        )

    # Robot Command

    ROBOT_GOTO_MIN_DISTANCE = (
        "/persistent/exts/isaacsim.replicator.agent/robot_goto_min_distance"
    )
    ROBOT_GOTO_MAX_DISTANCE = (
        "/persistent/exts/isaacsim.replicator.agent/robot_goto_max_distance"
    )

    @classmethod
    def get_robot_goto_min_distance(cls) -> Optional[float]:
        return CarbSettingUtil.get_value_by_key(
            key=cls.ROBOT_GOTO_MIN_DISTANCE, fallback_value=None
        )

    @classmethod
    def get_robot_goto_max_distance(cls) -> Optional[float]:
        return CarbSettingUtil.get_value_by_key(
            key=cls.ROBOT_GOTO_MAX_DISTANCE, fallback_value=None
        )

    @classmethod
    def set_robot_goto_min_distance(cls, value: float) -> None:
        CarbSettingUtil.set_value_by_key(
            key=cls.ROBOT_GOTO_MIN_DISTANCE, new_value=value
        )

    @classmethod
    def set_robot_goto_max_distance(cls, value: float) -> None:
        CarbSettingUtil.set_value_by_key(
            key=cls.ROBOT_GOTO_MAX_DISTANCE, new_value=value
        )
/isaac-sim/extscache/isaacsim.replicator.agent.core-0.7.28+107.3.3/isaacsim/replicator/agent/core/stage_util.py
from enum import Enum

import carb
import omni.usd
import omni.client
from isaacsim.core.utils import prims, semantics
from isaacsim.core.utils.rotations import lookat_to_quatf
from pxr import Gf, Sdf, Usd, UsdGeom

from .randomization.randomizer_util import RandomizerUtil
from .settings import Settings, AssetPaths, PrimPaths

from omni.anim.people.scripts.custom_command.populate_anim_graph import populate_anim_graph


class StageUtil:
    def open_stage(usd_path: str, ignore_unsave=True):
        if not Usd.Stage.IsSupportedFile(usd_path):
            raise ValueError("Only USD files can be loaded")
        import carb.settings
        import omni.kit.window.file

        IGNORE_UNSAVED_CONFIG_KEY = "/app/file/ignoreUnsavedStage"
        old_val = carb.settings.get_settings().get(IGNORE_UNSAVED_CONFIG_KEY)
        carb.settings.get_settings().set(IGNORE_UNSAVED_CONFIG_KEY, ignore_unsave)
        omni.kit.window.file.open_stage(usd_path, omni.usd.UsdContextInitialLoadSet.LOAD_ALL)
        carb.settings.get_settings().set(IGNORE_UNSAVED_CONFIG_KEY, old_val)

    # Set the xform transformation type to be Scale, Orient, Trans, and return the original order
    # NOTE::I am planning to move this part to the util extension, since the camera calibration require the same feature
    def set_xformOpType_SOT():
        xformoptype_setting_path = "/persistent/app/primCreation/DefaultXformOpType"
        original_xform_order_setting = carb.settings.get_settings().get(xformoptype_setting_path)
        carb.settings.get_settings().set(xformoptype_setting_path, "Scale, Orient, Translate")
        return original_xform_order_setting

    def recover_xformOpType(original_xform_order_setting):
        xformoptype_setting_path = "/persistent/app/primCreation/DefaultXformOpType"
        carb.settings.get_settings().set(xformoptype_setting_path, original_xform_order_setting)

    def fetch_semantic_label(target_prim, target_semantic_type: str = "class"):
        """fetch first semantic label with target type from the prim"""
        semantic_label = None
        # fetch all sematic labels attached on the object
        semantic_label_dict = semantics.get_semantics(target_prim)
        for key, type_to_vlaue in semantic_label_dict.items():
            semantic_type, semantic_value = tuple(type_to_vlaue)
            # ignore the case difference
            if str(semantic_type).lower() == target_semantic_type.lower():
                semantic_label = semantic_value
                break
        return semantic_label


class CameraUtil:
    def get_camera_name_by_index(i):
        if i == 0:
            return "Camera"
        elif i < 10:
            return "Camera_0" + str(i)
        else:
            return "Camera_" + str(i)

    def has_a_valid_name(name):
        if name == "Camera":
            return True
        # if name starts with "Camera"
        if name.startswith("Camera_"):
            return True
        return False

    def get_camera_name(camera_prim):
        return camera_prim.GetName()

    def get_camera_name_without_prefix(camera_prim):
        camera_name = None
        name = CameraUtil.get_camera_name(camera_prim)
        if name != None and CameraUtil.has_a_valid_name(name):
            if name == "Camera":
                return ""
            camera_name = name.split("_")[1]
        # camera_name will be None if invalid
        return camera_name

    def get_cameras_in_stage():
        camera_list = []
        # get camera root prim in the stage:
        camera_root_prim = CameraUtil.get_camera_root_prim()

        # if the camera root prim is not valid: return an emtpy list
        if camera_root_prim is None:
            return camera_list

        # all child camera prim would be added to the list:
        for camera_prim in camera_root_prim.GetChildren():
            if camera_prim.GetTypeName() == "Camera":
                camera_list.append(camera_prim)

        # then we sorted the camera prim base on their prim Name
        camera_list = sorted(camera_list, key=lambda camera: camera.GetName())
        return camera_list

    def set_camera(camera_prim, spawn_location=None, spawn_rotation=None, focallength=None):
        if spawn_location is None:
            spawn_location = Gf.Vec3d(0.0)

        if (not RandomizerUtil.aim_at_characters()) or (spawn_rotation is None):
            # Camera height is fixed in 5 by default
            camera_pos = Gf.Vec3d(spawn_location[0], spawn_location[1], 5)
        else:
            camera_pos = Gf.Vec3d(spawn_location[0], spawn_location[1], spawn_location[2])

        if spawn_rotation is None:
            # Camera will be always looking at the origin when it spawns
            spawn_rotation = Gf.Quatd(lookat_to_quatf(Gf.Vec3d(0.0), camera_pos, Gf.Vec3d(0, 0, 1)))

        camera_prim.GetAttribute("xformOp:orient").Set(spawn_rotation)
        camera_prim.GetAttribute("xformOp:translate").Set(camera_pos)

        if focallength is not None:
            camera_prim.GetAttribute("focalLength").Set(focallength)

    def spawn_camera(spawn_path=None, spawn_location=None, spawn_rotation=None, focallength=None):
        # set xformOp order to Scale, Orient, Translate, and store the setting
        original_xform_order_setting = StageUtil.set_xformOpType_SOT()
        stage = omni.usd.get_context().get_stage()
        camera_path = ""
        if spawn_path:
            camera_path = spawn_path
        else:
            camera_path = Sdf.Path(
                omni.usd.get_stage_next_free_path(stage, PrimPaths.cameras_parent_path() + "/Camera", False)
            )

        omni.kit.commands.execute("CreatePrimCommand", prim_type="Camera", prim_path=camera_path, select_new_prim=False)
        camera_prim = stage.GetPrimAtPath(camera_path)
        CameraUtil.set_camera(camera_prim, spawn_location, spawn_rotation, focallength)

        # set the xform setting back to original value
        StageUtil.recover_xformOpType(original_xform_order_setting)
        return camera_prim

    def delete_camera_prim(cam_name):
        stage = omni.usd.get_context().get_stage()
        if not Sdf.Path.IsValidPathString(PrimPaths.cameras_parent_path()):
            carb.log_error(str(PrimPaths.cameras_parent_path()) + "is not a valid prim path")
            return
        camera_prim = stage.GetPrimAtPath("{}/{}".format(PrimPaths.cameras_parent_path(), cam_name))
        if camera_prim and camera_prim.IsValid() and camera_prim.IsActive():
            prims.delete_prim(camera_prim.GetPath())

    def delete_camera_prims():
        camera_root_prim = CameraUtil.get_camera_root_prim()
        for camera_prim in camera_root_prim.GetChildren():
            if camera_prim and camera_prim.IsValid() and camera_prim.IsActive():
                prims.delete_prim(camera_prim.GetPath())

    def get_camera_root_prim():
        stage = omni.usd.get_context().get_stage()
        if not Sdf.Path.IsValidPathString(PrimPaths.cameras_parent_path()):
            carb.log_error(str(PrimPaths.cameras_parent_path()) + "is not a valid prim path")
            return None
        camera_root_prim = stage.GetPrimAtPath(PrimPaths.cameras_parent_path())
        if camera_root_prim and camera_root_prim.IsValid() and camera_root_prim.IsActive():
            return camera_root_prim

        carb.log_warn("No valid camera root prim exist.")
        return None


class StereoCamUtil:

    RIGHT_CAMERA_PREFIX = "_R"

    class Camera_Type(Enum):
        left_camera = 0
        right_camera = 1
        unknown = 2

    def get_camera_type(target_prim_path: str):
        """check whether the camera is a left camrea"""
        # In this demo version:  We use original camera set to generate stereo camera pair
        if target_prim_path.endswith(StereoCamUtil.RIGHT_CAMERA_PREFIX):
            return StereoCamUtil.Camera_Type.right_camera
        else:
            return StereoCamUtil.Camera_Type.left_camera

    def get_paired_stereo_camera_path(target_prim_path):
        """get target_camera_path as input, either left or right, get paired stereo camera path"""
        if StereoCamUtil.get_camera_type(target_prim_path) == StereoCamUtil.Camera_Type.left_camera:
            return target_prim_path + StereoCamUtil.RIGHT_CAMERA_PREFIX
        if StereoCamUtil.get_camera_type(target_prim_path) == StereoCamUtil.Camera_Type.right_camera:
            left_camera_prim_path = target_prim_path[: -len(StereoCamUtil.RIGHT_CAMERA_PREFIX)]
            return left_camera_prim_path


class LidarCamUtil:
    def get_lidar_name_by_index(i):
        if i == 0:
            return "Lidar"
        elif i < 10:
            return "Lidar_0" + str(i)
        else:
            return "Lidar_" + str(i)

    # check lidar name base on format
    def has_a_valid_name(name):
        if name == "Lidar":
            return True
        # if name starts with "Lidar"
        if name.startswith("Lidar_"):
            return True
        return False

    def get_lidar_name(lidar_prim):
        return lidar_prim.GetName()

    # return the actual name of the lidar camera, should be the part after "Lidar_"
    def get_lidar_name_without_prefix(lidar_prim):
        lidar_name = None
        name = LidarCamUtil.get_lidar_name(lidar_prim)
        # Return none if not a valid name
        if name != None and LidarCamUtil.has_a_valid_name(name):
            if name == "Lidar":
                return ""
            lidar_name = name.split("_")[1]
        return lidar_name

    # get lidar camera root prim
    def get_lidar_camera_root_prim():
        stage = omni.usd.get_context().get_stage()
        # if the lidar camera root prim does not exist, return empty list
        if not Sdf.Path.IsValidPathString(PrimPaths.lidar_cameras_parent_path()):
            carb.log_error(str(PrimPaths.lidar_cameras_parent_path()) + "is not a valid prim path")
            return None
        # fetch and return lidar camera root prim
        lidar_root_prim = stage.GetPrimAtPath(PrimPaths.lidar_cameras_parent_path())
        if lidar_root_prim and lidar_root_prim.IsValid() and lidar_root_prim.IsActive():
            return lidar_root_prim

        carb.log_warn("No valid camera root prim exist.")
        return None

    # get all camera prims under lidar camera root prim
    def get_lidar_cameras_in_stage():
        lidar_camera_list = []
        # get lidar camera root prim
        camera_root_prim = LidarCamUtil.get_lidar_camera_root_prim()
        # if the camera root prim is not valid: return an emtpy list
        if camera_root_prim is None:
            return lidar_camera_list

        # all child camera prim would be added to the list:
        for lidar_camera_prim in camera_root_prim.GetChildren():
            if lidar_camera_prim.GetTypeName() == "Camera":
                lidar_camera_list.append(lidar_camera_prim)

        lidar_camera_list = sorted(lidar_camera_list, key=lambda camera: camera.GetName())
        return lidar_camera_list

    # get all the lidar cameras that has a matching camera in stage
    def get_valid_lidar_cameras_in_stage():
        valid_lidar_camera_list = []
        lidar_camera_list = LidarCamUtil.get_lidar_cameras_in_stage()

        # For matching names with Lidar
        camera_list = CameraUtil.get_cameras_in_stage()

        # Check if they have a matching camera
        for lidar_camera in lidar_camera_list:
            lidar_name = LidarCamUtil.get_lidar_name_without_prefix(lidar_camera)
            has_match = False
            for camera in camera_list:
                if lidar_name == CameraUtil.get_camera_name_without_prefix(camera):
                    has_match = True
                    valid_lidar_camera_list.append(lidar_camera)
            if not has_match:
                carb.log_warn(LidarCamUtil.get_lidar_name(lidar_camera) + " has no matching camera")
        return valid_lidar_camera_list

    def spawn_lidar_camera(spawn_path=None, spawn_location=None, spawn_rotation=None, focallength=None):

        # ensure the default orientation system is base on orient system :
        original_xform_order_setting = StageUtil.set_xformOpType_SOT()

        stage = omni.usd.get_context().get_stage()

        camera_path = ""
        if spawn_path:
            camera_path = spawn_path
        else:
            camera_path = Sdf.Path(
                omni.usd.get_stage_next_free_path(stage, PrimPaths.lidar_cameras_parent_path() + "/Lidar", False)
            )

        camera_name = str(camera_path).replace(PrimPaths.lidar_cameras_parent_path(), "")
        camera_prim = stage.GetPrimAtPath(camera_path)

        lidar_config = "Example_Solid_State"
        _, sensor = omni.kit.commands.execute(
            "IsaacSensorCreateRtxLidar",
            path=camera_name,
            parent=PrimPaths.lidar_cameras_parent_path(),
            config=lidar_config,
        )

        camera_prim = stage.GetPrimAtPath(camera_path)
        CameraUtil.set_camera(camera_prim, spawn_location, spawn_rotation, focallength)

        # set the xform setting back to original value
        StageUtil.recover_xformOpType(original_xform_order_setting)
        return camera_prim

    # Delete one lidar camera prim by the given name
    def delete_lidar_camera_prim(cam_name):
        stage = omni.usd.get_context().get_stage()
        if not Sdf.Path.IsValidPathString(PrimPaths.lidar_cameras_parent_path()):
            carb.log_error(str(PrimPaths.lidar_cameras_parent_path()) + "is not a valid prim path")
            return
        lidar_camera_prim = stage.GetPrimAtPath("{}/{}".format(PrimPaths.lidar_cameras_parent_path(), cam_name))
        if lidar_camera_prim and lidar_camera_prim.IsValid() and lidar_camera_prim.IsActive():
            prims.delete_prim(lidar_camera_prim.GetPath())

    # Delete all lidar camera prims in the stage
    def delete_lidar_camera_prims():
        stage = omni.usd.get_context().get_stage()
        if not Sdf.Path.IsValidPathString(PrimPaths.lidar_cameras_parent_path()):
            carb.log_error(str(PrimPaths.lidar_cameras_parent_path()) + "is not a valid prim path")
            return
        lidar_camera_root_prim = stage.GetPrimAtPath(PrimPaths.lidar_cameras_parent_path())
        if lidar_camera_root_prim and lidar_camera_root_prim.IsValid() and lidar_camera_root_prim.IsActive():
            for lidar_camera_prim in lidar_camera_root_prim.GetChildren():
                if lidar_camera_prim and lidar_camera_prim.IsValid() and lidar_camera_prim.IsActive():
                    prims.delete_prim(lidar_camera_prim.GetPath())


class CharacterUtil:
    def get_character_skelroot_by_root(character_prim):
        for prim in Usd.PrimRange(character_prim):
            if prim.GetTypeName() == "SkelRoot":
                return prim
        return None

    def get_character_name_by_index(i):
        if i == 0:
            return "Character"
        elif i < 10:
            return "Character_0" + str(i)
        else:
            return "Character_" + str(i)

    def get_character_name(character_prim):
        # For characters under /World/Characters, names are root names
        # For the rest, names are skelroot names
        prim_path = prims.get_prim_path(character_prim)
        if prim_path.startswith(PrimPaths.characters_parent_path()):
            return prim_path.split("/")[3]
        else:
            return prim_path.split("/")[-1]

    def get_character_pos(character_prim):
        matrix = omni.usd.get_world_transform_matrix(character_prim)
        return matrix.ExtractTranslation()

    def get_characters_root_in_stage(count=-1, count_invisible=False):
        stage = omni.usd.get_context().get_stage()
        character_list = []
        character_root_path = PrimPaths.characters_parent_path()

        if stage is None:
            return []

        folder_prim = stage.GetPrimAtPath(character_root_path)

        if folder_prim is None or (not folder_prim.IsValid()) or (not folder_prim.IsActive()):
            return []

        children = folder_prim.GetAllChildren()
        for c in children:
            if len(character_list) >= count and count != -1:  # Get all if count is -1
                break
            if count_invisible == True or UsdGeom.Imageable(c).ComputeVisibility() != UsdGeom.Tokens.invisible:
                character_list.append(c)
        return character_list

    def get_characters_in_stage(count=-1, count_invisible=False):
        # Get a list of SkelRoot prims as characters
        stage = omni.usd.get_context().get_stage()
        character_root_path = PrimPaths.characters_parent_path()
        character_root = stage.GetPrimAtPath(character_root_path)
        character_list = []
        for prim in Usd.PrimRange(character_root):
            if len(character_list) >= count and count != -1:  # Get all if count is -1
                break
            if prim.GetTypeName() == "SkelRoot":
                if count_invisible == True or UsdGeom.Imageable(prim).ComputeVisibility() != UsdGeom.Tokens.invisible:
                    character_list.append(prim)
        return character_list

    def load_character_usd_to_stage(character_usd_path, spawn_location, spawn_rotation, character_stage_name):
        # ensure the default orientation system is base on orient system :
        original_xform_order_setting = StageUtil.set_xformOpType_SOT()
        stage = omni.usd.get_context().get_stage()
        # This automatically append number to the character name
        character_stage_name = omni.usd.get_stage_next_free_path(
            stage,
            f"{PrimPaths.characters_parent_path()}/{character_stage_name}",
            False,
        )
        # Load usd into stage and set character translation and rotation.
        prim = prims.create_prim(character_stage_name, "Xform", usd_path=character_usd_path)
        prim.GetAttribute("xformOp:translate").Set(
            Gf.Vec3d(float(spawn_location[0]), float(spawn_location[1]), float(spawn_location[2]))
        )
        if type(prim.GetAttribute("xformOp:orient").Get()) == Gf.Quatf:
            prim.GetAttribute("xformOp:orient").Set(
                Gf.Quatf(Gf.Rotation(Gf.Vec3d(0, 0, 1), float(spawn_rotation)).GetQuat())
            )
        else:
            prim.GetAttribute("xformOp:orient").Set(Gf.Rotation(Gf.Vec3d(0, 0, 1), float(spawn_rotation)).GetQuat())

        # set the xform setting back to original value
        StageUtil.recover_xformOpType(original_xform_order_setting)
        return prim

    def load_default_biped_to_stage():
        stage = omni.usd.get_context().get_stage()
        parent_path = PrimPaths.characters_parent_path()
        parent_prim = stage.GetPrimAtPath(parent_path)
        if not parent_prim.IsValid():
            prims.create_prim(parent_path, "Xform")
            carb.log_info(f"Character parent prim is created at: {parent_path}.")
            parent_prim = stage.GetPrimAtPath(parent_path)

        biped_prim_path = PrimPaths.biped_prim_path()
        biped_prim = stage.GetPrimAtPath(biped_prim_path)

        if Settings.skip_biped_setup():
            carb.log_info("Skip setting up Biped.")
            return biped_prim

        if not biped_prim.IsValid():
            prim = prims.create_prim(
                biped_prim_path,
                "Xform",
                usd_path=AssetPaths.default_biped_asset_path(),
            )
            prim.GetAttribute("visibility").Set("invisible")
            carb.log_info(
                f"Biped prim is created at: {biped_prim_path}, usd_path = {AssetPaths.default_biped_asset_path()}."
            )
            biped_prim = stage.GetPrimAtPath(biped_prim_path)

        populate_anim_graph()

        return biped_prim

    def get_anim_graph_from_character(character_prim):
        for prim in Usd.PrimRange(character_prim):
            if prim.GetTypeName() == "AnimationGraph":
                return prim
        return None

    def get_default_biped_character():
        stage = omni.usd.get_context().get_stage()
        return stage.GetPrimAtPath(PrimPaths.biped_prim_path())

    def setup_animation_graph_to_character(character_skelroot_list: list, anim_graph_prim):
        """
        Add animation graph for input characters in stage.
        Remove previous one if it exists
        """
        if anim_graph_prim is None or anim_graph_prim.IsValid() == False:
            carb.log_error("Unable to find an animation graph on stage.")
            return

        anim_graph_path = anim_graph_prim.GetPrimPath()
        paths = [Sdf.Path(prim.GetPrimPath()) for prim in character_skelroot_list]
        omni.kit.commands.execute("RemoveAnimationGraphAPICommand", paths=paths)
        omni.kit.commands.execute(
            "ApplyAnimationGraphAPICommand", paths=paths, animation_graph_path=Sdf.Path(anim_graph_path)
        )

    def setup_python_scripts_to_character(character_skelroot_list: list, python_script_path):
        """
        Add behavior script for input characters in stage.
        Remove previous one if it exists.
        """
        paths = [Sdf.Path(prim.GetPrimPath()) for prim in character_skelroot_list]
        omni.kit.commands.execute("RemoveScriptingAPICommand", paths=paths)
        omni.kit.commands.execute("ApplyScriptingAPICommand", paths=paths)
        for prim in character_skelroot_list:
            attr = prim.GetAttribute("omni:scripting:scripts")
            attr.Set([r"{}".format(python_script_path)])

    # Delete one character prim bt the given name
    def delete_character_prim(char_name):
        stage = omni.usd.get_context().get_stage()
        if not Sdf.Path.IsValidPathString(PrimPaths.characters_parent_path()):
            carb.log_error(str(PrimPaths.characters_parent_path()) + " is not a valid prim path")
            return

        character_prim = stage.GetPrimAtPath("{}/{}".format(PrimPaths.characters_parent_path(), char_name))
        if character_prim and character_prim.IsValid() and character_prim.IsActive():
            prims.delete_prim(character_prim.GetPath())

    # Delete all character prims in the stage
    def delete_character_prims():
        """
        Delete previously loaded character prims. Also deletes the default skeleton and character animations if they
        were loaded using load_default_skeleton_and_animations. Also deletes state corresponding to characters
        loaded onto stage.
        """
        stage = omni.usd.get_context().get_stage()
        if not Sdf.Path.IsValidPathString(PrimPaths.characters_parent_path()):
            carb.log_error(str(PrimPaths.characters_parent_path()) + " is not a valid prim path")
            return

        character_root_prim = stage.GetPrimAtPath(PrimPaths.characters_parent_path())
        if character_root_prim and character_root_prim.IsValid() and character_root_prim.IsActive():
            for character_prim in character_root_prim.GetChildren():
                if character_prim and character_prim.IsValid() and character_prim.IsActive():
                    prims.delete_prim(character_prim.GetPath())


class RobotUtil:
    WORLD_SETTINGS = {"physics_dt": 1.0 / 30.0, "stage_units_in_meters": 1.0, "rendering_dt": 1.0 / 30.0}

    def get_robot_name_by_index(robot_type, i):
        if i == 0:
            return robot_type
        elif i < 10:
            return robot_type + "_0" + str(i)
        else:
            return robot_type + "_" + str(i)

    def get_robot_name(robot_prim):
        # For robots under /World/Robots, names are root names
        prim_path = prims.get_prim_path(robot_prim)
        if prim_path.startswith(PrimPaths.robots_parent_path()):
            return prim_path.split("/")[3]

    def get_robot_pos(robot_prim):
        matrix = omni.usd.get_world_transform_matrix(robot_prim)
        return matrix.ExtractTranslation()

    def get_robots_in_stage(count=-1, robot_type_name=None):
        robot_xform = prims.get_prim_at_path(PrimPaths.robots_parent_path())
        if not robot_xform.IsValid() or not robot_xform.IsActive():
            return []
        prims_under_robots = prims.get_prim_children(robot_xform)
        robot_list = []
        for prim in prims_under_robots:
            if len(robot_list) >= count and count != -1:  # Get all if count is -1
                break
            path = prims.get_prim_path(prim)
            if robot_type_name == None:
                robot_list.append(prim)
            else:
                if path.startswith(PrimPaths.robots_parent_path() + "/" + robot_type_name):
                    robot_list.append(prim)
        return robot_list

    # Get all the cameras on the given robot
    def get_cameras_on_robot(robot_prim):
        stage = omni.usd.get_context().get_stage()
        robot_path = prims.get_prim_path(robot_prim)
        camera_list = []
        for prim in stage.Traverse():
            path = prims.get_prim_path(prim)
            if prim.GetTypeName() == "Camera" and path.startswith(robot_path):
                camera_list.append(prim)
        return camera_list

    # Get all the lidar cameras on the given robot
    def get_lidar_cameras_on_robot(robot_prim):
        stage = omni.usd.get_context().get_stage()
        robot_path = prims.get_prim_path(robot_prim)
        camera_list = []
        for prim in stage.Traverse():
            path = prims.get_prim_path(prim)
            if prim.GetTypeName() == "Camera" and path.startswith(robot_path) and "LIDAR" in path.split("/")[-1]:
                camera_list.append(prim)
        return camera_list

    # Get all the cameras on all the robots in the stage
    def get_robot_cameras():
        cameras = [cam for robot in RobotUtil.get_robots_in_stage() for cam in RobotUtil.get_cameras_on_robot(robot)]
        return cameras

    # Get the fisrt n cameras on all the robots in the stage
    def get_n_robot_cameras(n):
        cameras = [
            cam for robot in RobotUtil.get_robots_in_stage() for cam in RobotUtil.get_cameras_on_robot(robot)[:n]
        ]
        return cameras

    # Get all the lidar cameras on all the robots in the stage
    def get_robot_lidar_cameras():
        lidars = [
            lidar for robot in RobotUtil.get_robots_in_stage() for lidar in RobotUtil.get_lidar_cameras_on_robot(robot)
        ]
        return lidars

    # Get all the lidar cameras on all the robots in the stage
    def get_n_robot_lidar_cameras(n):
        lidars = [
            lidar
            for robot in RobotUtil.get_robots_in_stage()
            for lidar in RobotUtil.get_lidar_cameras_on_robot(robot)[:n]
        ]
        return lidars

    def spawn_robot(spawn_type, spawn_location, spawn_rotation=0, spawn_path=None):

        # ensure the default orientation system is base on orient system :
        original_xform_order_setting = StageUtil.set_xformOpType_SOT()
        stage = omni.usd.get_context().get_stage()

        # This automatically append number to the robot name
        robot_stage_name = omni.usd.get_stage_next_free_path(
            stage, f"{PrimPaths.robots_parent_path()}/{spawn_type}", False
        )
        if spawn_path:
            robot_stage_name = spawn_path
        # Create a prim in the stage and set the translation and rotation.
        prim = prims.create_prim(robot_stage_name, "Xform")
        prim.GetAttribute("xformOp:translate").Set(
            Gf.Vec3d(float(spawn_location[0]), float(spawn_location[1]), float(spawn_location[2]))
        )
        if type(prim.GetAttribute("xformOp:orient").Get()) == Gf.Quatf:
            prim.GetAttribute("xformOp:orient").Set(
                Gf.Quatf(Gf.Rotation(Gf.Vec3d(0, 0, 1), float(spawn_rotation)).GetQuat())
            )
        else:
            prim.GetAttribute("xformOp:orient").Set(Gf.Rotation(Gf.Vec3d(0, 0, 1), float(spawn_rotation)).GetQuat())

        # set the xform setting back to original value
        StageUtil.recover_xformOpType(original_xform_order_setting)

        return prim

    # Delete one character prim bt the given name
    def delete_robot_prim(robot_name):
        stage = omni.usd.get_context().get_stage()
        if not Sdf.Path.IsValidPathString(PrimPaths.robots_parent_path()):
            carb.log_error(str(PrimPaths.robots_parent_path()) + " is not a valid prim path")
            return

        robot_prim = stage.GetPrimAtPath("{}/{}".format(PrimPaths.robots_parent_path(), robot_name))
        if robot_prim and robot_prim.IsValid() and robot_prim.IsActive():
            prims.delete_prim(robot_prim.GetPath())

    # Delete all character prims in the stage
    def delete_robot_prims():
        """
        Delete previously loaded character prims. Also deletes the default skeleton and character animations if they
        were loaded using load_default_skeleton_and_animations. Also deletes state corresponding to characters
        loaded onto stage.
        """
        stage = omni.usd.get_context().get_stage()
        if not Sdf.Path.IsValidPathString(PrimPaths.robots_parent_path()):
            carb.log_error(str(PrimPaths.robots_parent_path()) + " is not a valid prim path")
            return

        robot_root_prim = stage.GetPrimAtPath(PrimPaths.robots_parent_path())
        if robot_root_prim and robot_root_prim.IsValid() and robot_root_prim.IsActive():
            for robot_prim in robot_root_prim.GetChildren():
                if robot_prim and robot_prim.IsValid() and robot_prim.IsActive():
                    prims.delete_prim(robot_prim.GetPath())


class AgentUtil:
    def get_all_agents_positions():
        """
        Get all agent positions in stage.
        """
        positions = []
        # Characters
        characters = CharacterUtil.get_characters_root_in_stage()
        for char in characters:
            positions.append(CharacterUtil.get_character_pos(char))
        # Robots
        robots = RobotUtil.get_robots_in_stage(-1)
        for robot in robots:
            positions.append(RobotUtil.get_robot_pos(robot))
        return positions
