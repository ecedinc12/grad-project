import asyncio
import re
import os
import carb.settings
import omni.kit
import omni.kit.test
import omni.usd
from omni.metropolis.utils.unit_test import (
    NAVMESH_AREA_TEST_STAGE_URL,
    TestStage,
    StageSetupOptions,
    context_create_example_sim_manager,
    wait_for_simulation_set_up_done,
)
import AnimGraphSchema
from isaacsim.replicator.agent.core.randomization.randomizer_util import RandomizerUtil
from isaacsim.replicator.agent.core.settings import BehaviorScriptPaths, PrimPaths
from isaacsim.replicator.agent.core.simulation import SimulationManager
from isaacsim.replicator.agent.core.stage_util import CameraUtil, CharacterUtil, LidarCamUtil, RobotUtil
from pxr import Usd, UsdGeom


class TestSimulation(omni.kit.test.AsyncTestCase):
    async def setUp(self):
        pass

    async def tearDown(self):
        pass

    async def test_load_save_command_file(self):
        """
        Test character and robot command files can be loaded and saved through SimulationManager
        """
        with context_create_example_sim_manager() as sim:
            # Change contentes in command files
            test_commands_list = ["Character Idle 5"]
            test_robot_commands_list = ["Carter Idle 5"]
            sim.save_commands(test_commands_list)
            sim.save_robot_commands(test_robot_commands_list)
            # Check if the changes are saved
            commands_list = sim.load_commands()
            robot_commands_list = sim.load_robot_commands()
            self.assertListEqual(test_commands_list, commands_list)
            self.assertListEqual(test_robot_commands_list, robot_commands_list)

    async def test_load_scene(self):
        """
        Test if scenes can be loaded correctly through SimulationManager
        """
        # On an empty scene
        with context_create_example_sim_manager() as sim:
            # Simulation Manager loads the default scene
            prop = sim.get_config_file_property("character", "num")
            prop.set_value(0)
            group = sim.get_config_file_property_group("sensor", "camera_group")
            group.get_property("camera_num").set_value(0)
            # group.get_property("lidar_num").set_value(0)
            # Wait for simulation set up done
            sim.set_up_simulation_from_config_file()
            await wait_for_simulation_set_up_done(sim)
            # Check if the default scene is loaded
            current_url = omni.usd.get_context().get_stage_url()

            def normalize_path(p):
                # If it's a Windows file path (starts with a drive letter), normalize case and separators
                if re.match(r"^[a-zA-Z]:[\\/]", p):
                    return os.path.normcase(os.path.normpath(p))
                return p  # leave URLs or non-Windows paths untouched

            self.assertEqual(normalize_path(current_url), normalize_path(sim.get_config_file_property("scene", "asset_path").get_value()))

    # ======= Test Characters ========

    async def test_load_default_skeleton_and_animations(self):
        """
        Test if default skeletons and animations can be loaded through SimulationManager
        """
        async with TestStage():
            sim = SimulationManager()  # noqa
            CharacterUtil.load_default_biped_to_stage()
            stage = omni.usd.get_context().get_stage()
            setting_dict = carb.settings.get_settings()  # noqa
            self.characters_parent_prim_path = PrimPaths.characters_parent_path()
            self.assertTrue(stage.GetPrimAtPath(f"{self.characters_parent_prim_path}").IsValid())
            self.assertTrue(stage.GetPrimAtPath(f"{self.characters_parent_prim_path}/Biped_Setup").IsValid())
            self.assertTrue(
                stage.GetPrimAtPath(f"{self.characters_parent_prim_path}/Biped_Setup/CharacterAnimation").IsValid()
            )
            self.assertTrue(
                stage.GetPrimAtPath(f"{self.characters_parent_prim_path}/Biped_Setup/biped_demo_meters").IsValid()
            )

    async def test_load_characters(self):
        """
        Test if correct amounts of characters can be loaded
        """
        # On an empty scene
        with context_create_example_sim_manager() as sim:
            # Load 5 default characters from default characters folder into default scene
            prop = sim.get_config_file_property("character", "num")
            prop.set_value(5)
            # Wait for simulation set up done
            sim.set_up_simulation_from_config_file()
            await wait_for_simulation_set_up_done(sim)
            # Check if 5 characters are loaded
            stage = omni.usd.get_context().get_stage()  # noqa
            char_list = CharacterUtil.get_characters_root_in_stage()
            self.assertEqual(len(char_list), 5)
            # Reduce number to 3, check if the last 2 are not deleted
            prop.set_value(3)
            sim.load_characters_from_config_file()
            char_list = CharacterUtil.get_characters_root_in_stage()
            self.assertEqual(len(char_list), 5)
            # Increase character numbers to 7, check if the additional 2 are spawned
            prop.set_value(7)
            sim.load_characters_from_config_file()
            char_list = CharacterUtil.get_characters_root_in_stage()
            self.assertEqual(len(char_list), 7)

    async def test_setup_characters(self):
        """
        Test if behavior scripts and animation graphs have been setup to each character
        """
        # On an empty scene
        async with TestStage():
            with context_create_example_sim_manager() as sim:
                # Load 5 characters to default scene
                prop = sim.get_config_file_property("character", "num")
                prop.set_value(5)
                # Wait for simulation set up done
                sim.set_up_simulation_from_config_file()
                await wait_for_simulation_set_up_done(sim)
                # Go through each character
                skelroot_list = CharacterUtil.get_characters_in_stage()
                self.assertEqual(len(skelroot_list), 5)
                # Python scripts
                script_path = BehaviorScriptPaths.behavior_script_path()
                # Animation graph
                default_biped = CharacterUtil.get_default_biped_character()
                anim_graph_path = CharacterUtil.get_anim_graph_from_character(default_biped).GetPrimPath()
                for skelroot in skelroot_list:
                    attr = skelroot.GetAttribute("omni:scripting:scripts").Get()
                    self.assertEqual(attr[0].path, script_path)
                    anim_graph_ref = AnimGraphSchema.AnimationGraphAPI(skelroot).GetAnimationGraphRel()
                    self.assertEqual(anim_graph_ref.GetTargets()[0], anim_graph_path)

    # ======= Test Camera Randomization ========
    # The following code aiming at testing whether Camera Randomization Works
    async def test_random_camera_height(self):
        """
        Test if all the camera's height are in range defined by user
        """
        # get the original camera_randomization setting:
        # (we need to reset this value at the end of test)
        original_aim_character_setting = RandomizerUtil.aim_at_characters()
        RandomizerUtil.set_aim_cameras_at_characters(True)
        max_camera_height = RandomizerUtil.get_max_camera_height()
        min_camera_height = RandomizerUtil.get_min_camera_height()
        xformoptype_setting_path = "/persistent/app/primCreation/DefaultXformOpType"
        original_xform_order_setting = carb.settings.get_settings().get(xformoptype_setting_path)
        carb.settings.get_settings().set(xformoptype_setting_path, "Scale, Orient, Translate")
        carb.settings.get_settings().set(RandomizerUtil.MAX_CAMERA_FOCALLENGTH, 23)
        carb.settings.get_settings().set(RandomizerUtil.MIN_CAMERA_FOCALLENGTH, 13)

        # On an empty scene
        with context_create_example_sim_manager() as sim:
            prop = sim.get_config_file_property("character", "num")
            prop.set_value(20)
            prop_group = sim.get_config_file_property_group("sensor", "camera_group")
            prop_group.get_property("camera_num").set_value(5)
            sim.set_up_simulation_from_config_file()
            await wait_for_simulation_set_up_done(sim)
            stage = omni.usd.get_context().get_stage()
            camera_root_prim = stage.GetPrimAtPath(PrimPaths.cameras_parent_path())
            if camera_root_prim is None:
                carb.log_error("no valid camera in the scene")
                return False
            for prim in Usd.PrimRange(camera_root_prim):
                if prim.IsA(UsdGeom.Camera):
                    translate_value = prim.GetAttribute("xformOp:translate").Get()
                    self.assertLessEqual(min_camera_height <= translate_value[2], max_camera_height)

            RandomizerUtil.set_aim_cameras_at_characters(original_aim_character_setting)
            carb.settings.get_settings().set(xformoptype_setting_path, original_xform_order_setting)

    async def test_random_camera_focallength(self):
        """
        Test if all the camera's focal length are in range defined by user
        """
        # get the original camera_randomization setting:
        # (we need to reset this value at the end of test)
