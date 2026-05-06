# flake8: noqa
import asyncio
import json
from pathlib import Path

import carb
import numpy as np
import omni.anim.navigation.core as nav
import omni.client
import omni.kit
import omni.usd
from omni.metropolis.utils.debug_util import DebugPrint
from omni.metropolis.utils.file_util import CommandFileUtil, FileUtil
from omni.metropolis.utils.semantics_util import SemanticsUtils
from pxr import Sdf

import NavSchema

from omni.metropolis.utils.config_file.core import ConfigFile
from .data_generation.data_generation import DataGeneration
from .randomization.camera_randomizer import CameraRandomizer
from .randomization.carter_randomizer import CarterRandomizer
from .randomization.character_randomizer import CharacterRandomizer
from .randomization.randomizer_util import RandomizerUtil
from .randomization.iw_hub_randomizer import IwHubRandomizer
from .response.core import AgentResponseManager
from .settings import AssetPaths, PrimPaths, BehaviorScriptPaths, Settings, GlobalValues
from .stage_util import CameraUtil, CharacterUtil, RobotUtil, StageUtil, AgentUtil
from .incident_bridge import IncidentBridge

FRAME_RATE = 30

OMNI_ANIM_PEOPLE_COMMAND_PATH = "/exts/omni.anim.people/command_settings/command_file_path"
ANIM_ROBOT_COMMAND_PATH = "/exts/isaacsim.anim.robot/command_settings/command_file_path"

dp = DebugPrint(Settings.DEBUG_PRINT, "SimulationManager")


class SimulationManager:
    """
    Simulation Manager class that takes in config file to set up simulation accordingly.
    """

    SET_UP_SIMULATION_DONE_EVENT = "isaacsim.replicator.agent.SET_UP_SIMULATION_DONE"
    DATA_GENERATION_DONE_EVENT = "isaacsim.replicator.agent.DATA_GENERATION_DONE_EVENT"

    def __init__(self):
        self.character_assets_list = (
            []
        )  # List of all characters inside the character asset folders, provided by config file
        self.available_character_list = []  # Character list after filtering and shuffling
        # Config file variables
        self.config_file: ConfigFile = None
        # Randomizers
        self._character_randomizer = CharacterRandomizer(0)
        self._nova_carter_randomizer = CarterRandomizer(0)
        self._iw_hub_randomizer = IwHubRandomizer(0)
        self._camera_randomizer = CameraRandomizer(0)
        self._agent_positions = []
        # State variables for assets loading
        self._load_stage_handle = None
        # Incident bridge
        self._incident_bridge = IncidentBridge()
        self._dg = None
        self._dg_task = None

    # ========= Set Up Characters/Robots =========

    def load_filters(self):
        """
        Load the filters from the asset folder
        The filter must be a json file named "filter" and located in the asset root directory
        """
        if not self.config_file:
            return None
        prop = self.config_file.get_property("character", "asset_path")
        if not prop:
            carb.log_error("Unable to get character asset path. Will not load filter file.")
            return None
        if prop.is_value_error():
                else:
                    if label != "" and label != " ":  # noqa
                        carb.log_warn(
                            f'Invalid character filter label: "{label}". Available labels: {", ".join(filters.keys())}'
                        )
                        labels.remove(label)
            self.available_character_list = filtered

    @dp.debug_func
    def setup_python_scripts_to_robot(self, robot_list, robot_type):
        """
        Add behavior script to all characters in stage
        """
        script_path = BehaviorScriptPaths.robot_behavior_script_path(robot_type)
        dp.print(f"To use behavior script: {script_path}.")
        for prim in robot_list:
            omni.kit.commands.execute("ApplyScriptingAPICommand", paths=[Sdf.Path(prim.GetPrimPath())])
            attr = prim.GetAttribute("omni:scripting:scripts")
            # Get the corresponding robot script
            attr.Set([f"{script_path}"])
            dp.print(f"Set up python script for robot, prim = {prim.GetPrimPath()}.")

    def refresh_randomizers(self):
        """
        Refresh randomizers with global seed.
        """
        prop = self.config_file.get_property("global", "seed")
        if prop.is_value_error():
            carb.log_error("Refresh randomizers fails due to invalid global seed.")
            return
        seed = prop.get_resolved_value()
        self._character_randomizer.update_seed(seed)
        self._camera_randomizer.update_seed(seed)
        self._nova_carter_randomizer.update_seed(seed)
        self._iw_hub_randomizer.update_seed(seed)

    # ========= Config File =========

    def load_config_file(self, file_path):
        """
        Load config file object by input file path.
        """
        self.config_file = GlobalValues.config_file_format.load_config_file(file_path)
        if not self.config_file:
            carb.log_error(f"Config file cannot be loaded from: {file_path}.")
            return False
        self._on_config_file_loaded()
        return True

    def _on_config_file_loaded(self):
        # Register property listeners
        # Set up agent randomizer
        agents_pos = AgentUtil.get_all_agents_positions()
        self._character_randomizer.update_agent_positions(agents_pos)

        # Get stage and paths
        stage = omni.usd.get_context().get_stage()
        parent_path = PrimPaths.characters_parent_path()
        spawn_area = self.get_config_file_valid_value("character", "spawn_area")
        for i in range(character_count):
            character_name = CharacterUtil.get_character_name_by_index(i)
            character_path = f"{parent_path}/{character_name}"
            character_prim = stage.GetPrimAtPath(character_path)
            if not character_prim.IsValid():
                new_pos = self._character_randomizer.get_random_position(spawn_area)
                character_prim = self.spawn_character_by_idx(new_pos, 0, i)
                if not character_prim:
                    carb.log_error(f"Failed to spawn character {character_name}.")
                    continue
                carb.log_info(f"Spawned character {character_name} at position {new_pos}.")
            else:
                carb.log_info(f"Character already exists: {character_path}")

            # Apply NavMesh API
            omni.kit.commands.execute(
                "ApplyNavMeshAPICommand", prim_path=character_path, api=NavSchema.NavMeshExcludeAPI
            )

    def setup_all_characters(self):
        """
        Set up all characters in stage (anim graph, python script, semantic)
        """
        biped_prim = CharacterUtil.load_default_biped_to_stage()
        character_list = CharacterUtil.get_characters_in_stage()
        CharacterUtil.setup_animation_graph_to_character(
            character_list, CharacterUtil.get_anim_graph_from_character(biped_prim)
        )
        CharacterUtil.setup_python_scripts_to_character(character_list, BehaviorScriptPaths.behavior_script_path())
        SemanticsUtils.add_update_prim_metrosim_semantics(character_list, type_value="class", name="character")

    def get_character_randomizer(self) -> CharacterRandomizer:
        return self._character_randomizer
