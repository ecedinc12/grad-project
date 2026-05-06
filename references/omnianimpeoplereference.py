# Copyright (c) 2022, NVIDIA CORPORATION.  All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto.  Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.

import asyncio

import carb
import omni.ext
import omni.kit.app
import omni.ui
from omni.anim.people.scripts.custom_command.command_manager import CustomCommandManager
from pxr import Sdf

_extension_instance = None
_ext_id = None
_ext_path = None


def get_instance():
    return _extension_instance


def get_ext_id():
    return _ext_id


def get_ext_path():
    return _ext_path

def add_dynamic_obstacle_behavior_script(prim_path):
    carb.log_info(f"[OAP] Adding dynamic obstacle behavior script to {prim_path}")
    script_path = (
        omni.kit.app.get_app().get_extension_manager().get_extension_path_by_module("omni.anim.people")
        + "/omni/anim/people/scripts/dynamic_obstacle.py"
    )

    stage = omni.usd.get_context().get_stage()
    prim = stage.GetPrimAtPath(prim_path)

    omni.kit.commands.execute("ApplyScriptingAPICommand", paths=[Sdf.Path(prim_path)])
    attr = prim.GetAttribute("omni:scripting:scripts")
    script_list_usd = attr.Get()
    script_list = [r"{}".format(script_path)]

    if script_list_usd:
        for script_path in script_list_usd:
            script_list.append(script_path)

    attr.Set(script_list)

class Main(omni.ext.IExt):
    def on_startup(self, ext_id):
        carb.log_info("[omni.anim.people] startup")
        global _extension_instance
        _extension_instance = self
        global _ext_id
        _ext_id = ext_id
        global _ext_path
        _ext_path = omni.kit.app.get_app().get_extension_manager().get_extension_path(ext_id)
        # Custom command manager
        self._cmd_manager = CustomCommandManager(_ext_path)
        self._cmd_manager.startup()

    def on_shutdown(self):
        carb.log_info("[omni.anim.people] shutdown")
        global _extension_instance
        _extension_instance = None
        global _ext_id
        _ext_id = None
        global _ext_path
        _ext_path = None

        self._cmd_manager.shutdown()
        self._cmd_manager = None

    def get_custom_command_manager(self):
        return self._cmd_manager
=== /isaac-sim/extscache/omni.anim.people-0.7.9+107.3.3/omni/anim/people/scripts/character_behavior.py ===
# Copyright (c) 2022, NVIDIA CORPORATION.  All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto.  Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.

# flake8: noqa

from __future__ import annotations

import importlib
import math

from typing import List, Callable, Tuple, Dict

import carb
import omni.anim.graph.core as ag
import omni.usd
from omni.anim.people.python_ext import get_instance

from omni.anim.people.scripts.custom_command.command_manager import *
from omni.anim.people.scripts.custom_command.command_templates import *
from omni.anim.people.scripts.global_queue_manager import GlobalQueueManager
from omni.anim.people.scripts.navigation_manager import NavigationManager
from omni.anim.people.settings import AgentEvent, PeopleSettings, TaskStatus
from omni.kit.scripting import BehaviorScript

from .commands.dequeue import *
from .commands.goto import *
from .commands.idle import *
from .commands.look_around import *
from .commands.queue import *
from .commands.sit import *
from .commands.goto_section import *
from .commands.goto_object import *
from .utils import Utils

COMMAND_CALLBCAK_CHECKPOINT = "COMMAND_CALLBCAK_CHECKPOINT"


class CharacterBehavior(BehaviorScript):
    """
    Character controller class that reads commands from a command file and drives character actions.
    """

    def on_init(self):
        """
        Called when a script is attached to characters and when a stage is loaded. Uses renew_character_state() to initialize character state.
        """
        self._overwrite_command_file = None
        self._overwrite_agent_name = None
        self.renew_character_state()

    def on_play(self):
        """
        Called when entering runtime (when clicking play button). Uses renew_character_state() to initialize character state.
        """
        self.renew_character_state()

    def on_stop(self):
        """
        Called when exiting runtime (when clicking stop button). Uses on_destroy() to clear state.
        """
        self.on_destroy()

    def on_destroy(self):
        """
        Clears character state by deleting global variable instances.
        """

        self.current_command = None

        self.character_name = None
        if self.navigation_manager is not None:
            self.navigation_manager.destroy()
            self.navigation_manager = None

        if self.queue_manager is not None:
            self.queue_manager.destroy()
            self.queue_manager = None

    def renew_character_state(self):
        """
        Defines character variables and loads settings.
        """
        self.setting = carb.settings.get_settings()
        if self._overwrite_command_file:
            self.command_path = self._overwrite_command_file
        else:
            self.command_path = self.setting.get(PeopleSettings.COMMAND_FILE_PATH)
        self.number_of_loop = self.setting.get_as_string(PeopleSettings.NUMBER_OF_LOOP)
        if self.number_of_loop == "inf":
            self.number_of_loop = math.inf
        else:
            self.number_of_loop = int(self.number_of_loop)
        self.navmeshEnabled = self.setting.get(PeopleSettings.NAVMESH_ENABLED)
        self.avoidanceOn = self.setting.get(PeopleSettings.DYNAMIC_AVOIDANCE_ENABLED)
        self.character_name = self.get_agent_name()
        carb.log_info("Character name is {}".format(self.character_name))
        self.character = None
        self.current_command = None
        self.loop_commands = None
        self.loop_commands_count = 1
        self.navigation_manager = None
        self.queue_manager = None
        self.global_character_manager = None
        self.in_queue = False
        self.commands = []
        self.interruptable = True
        # Inject command related
        self._command_callback_checkpoint: Dict[str, Callable[[str, str], None]] = {}

    # force the character to end current command
    def end_current_command(self, set_status: bool = True):

        # if current command is not None, force the character to quit.
        if self.current_command is not None:

            if set_status:
                self.current_command.set_status(TaskStatus.interrupted)
            self.current_command.force_quit_command()

            # if character is conducting "Queue" command, remove next several commands related to this behavior.
            if self.current_command.get_command_name() == "QueueCmd" or self.in_queue:
                self.clean_unclosed_dequeue()

        # if character is currently inside the queue, remove character from the queue.
        if self.in_queue:
            # Free the queue spot occupied by this character.
            self.queue_manager.remove_character_from_queue(str(self.character_name))
            self.in_queue = None

    # Remove the following queue behavior and "Dequeue" command once the "Queue" command is interrupted by command injection
    def clean_unclosed_dequeue(self):
        if len(self.commands) > 1:
            list_length = len(self.commands)
            for i in range(1, list_length):
                # if we hit the "Queue" command
                if str(self.commands[i][0]) == "Queue":
                    break
                # if we hit uncompleted Dequeue command.
                if str(self.commands[i][0]) == "Dequeue":
                    # remove all the command between this command and the second command.
                    if i == 1:
                        self.commands.pop(i)
                    else:
                        self.commands[1:i] = []
                    break

    def get_agent_name(self):
        """
        For this character asset find its name used in the command file.
        """
        if self.overwrite_agent_name is not None:
            return self.overwrite_agent_name
        character_path = str(self.prim_path)
        split_path = character_path.split("/")
        root_path = self.setting.get(PeopleSettings.CHARACTER_PRIM_PATH)
        # If a character is loaded through the spawn command, the commands for the character can be given by using the encompassing parent name.
        if character_path.startswith(str(root_path)):
            parent_len = len(root_path.split("/"))
            parent_name = split_path[parent_len]
            return parent_name
        else:
            carb.log_error(
                f"Cannot find character with behavior script attaches on {str(self.prim_path)} under character root primn. "
            )

        return None

    def register_to_agent_manager(self):
        """
        Passing the agent data to AgentManager so it can be registered
        """
        agent_name = self.get_agent_name()
        command_info = {"agent_name": str(agent_name), "prim_path": str(self.prim_path)}
        carb.eventdispatcher.get_eventdispatcher().dispatch_event(
            event_name=AgentEvent.AgentRegistered, payload=command_info
        )
        carb.log_info("register to agent manager : -- {agent_name}".format(agent_name=agent_name))

    def init_character(self):
        """
        Initializes global variables and fetches animation graph attached to the character. Called after entering runtime as ag.get_character() can only be used in runtime.
        """
        self.character = ag.get_character(str(self.prim_path))
        if self.character is None:
            return False

        self.custom_command_manager = get_instance().get_custom_command_manager()
        self.navigation_manager = NavigationManager(str(self.prim_path), self.navmeshEnabled, self.avoidanceOn)
        self.queue_manager = GlobalQueueManager.get_instance()
        if not self.navigation_manager or not self.queue_manager:
            return False

        # event for agent's register
        self.commands = self.get_simulation_commands()

        # Store all registered custom commands beforehand
        self.custom_command_names = self.custom_command_manager.get_all_custom_command_names()

        # Prepare loop command
        if self.number_of_loop > 0:
            # Character go to original spot to form the loop
            originPos, originRot = Utils.get_character_transform(self.character)
            originAngle = Utils.convert_to_angle(originRot)
            self.commands.append(
                (None, ["GoTo", str(originPos[0]), str(originPos[1]), str(originPos[2]), str(originAngle)])
            )
            self.loop_commands = self.commands.copy()

        self.character.set_variable("Action", "None")
        carb.log_info("Initialize the character")
        return True

    def subscription_to_command_start(self, current_command: Command):
        """
        fetch command information and input in a event:
        """
        command_info = {}
        if current_command is not None:
            command_info = current_command.fetch_command_info()
        carb.eventdispatcher.get_eventdispatcher().dispatch_event(
            event_name=AgentEvent.CommandStartEvent, payload=command_info,
        )
        carb.log_info(
            "create event: -- command start with command info: {command_info}".format(command_info=str(command_info))
        )

    def subscription_to_command_end(self, current_command: Command, status: str | None = None):
        """
        fetch command information and input in a event:
        """
        command_info = {}
        if current_command is not None:
            command_info = current_command.fetch_command_info()

        if status is not None:
            command_info["status"] = status

        carb.eventdispatcher.get_eventdispatcher().dispatch_event(
            event_name=AgentEvent.CommandEndEvent, payload=command_info
        )
        carb.log_info(
            "create event: -- command end with command info: {command_info}".format(command_info=str(command_info))
        )

    def set_metadata_callback(self, agent_name: str, data_name: str, data_value: str):
        """submit event to update character's metadata info"""
        # check whether the metadata need to be cached every frame:
        cache_metadata = carb.settings.get_settings().get(PeopleSettings.CACHE_ACTION_METADATA)
        if not cache_metadata:
            return

        # compose nucessary information to update the metadata info:
        agent_metadata_info = {"agent_name": agent_name, "data_name": data_name, "data_value": data_value}
        # dispatch the event to update character metadata.
        carb.eventdispatcher.get_eventdispatcher().dispatch_event(
            event_name=AgentEvent.MetadataUpdateEvent, payload=agent_metadata_info
        )
        pass

    def read_commands_from_file(self):
        """
        Reads commands from file pointed by self.command_path. Creates a Queue using queue manager if a queue is specified.
        :return: List of commands.
        :rtype: python list
        """
        if not self.command_path:
            carb.log_warn("Command file field is empty.")
            return []
        result, version, context = omni.client.read_file(self.command_path)
        if result != omni.client.Result.OK:
            carb.log_error("Unable to read command file at {}.".format(self.command_path))
            return []

        cmd_lines = memoryview(context).tobytes().decode("utf-8").splitlines()
        return cmd_lines

    def get_combined_user_commands(self):
        cmd_lines = []

        # Get commands from cmd_file
        cmd_lines.extend(self.read_commands_from_file())

        return cmd_lines

    # convert command string to command list. split character name, command name, and command parameters
    def convert_str_to_command(self, cmd_line):
        if not cmd_line:
            return None
        words = str(cmd_line).strip().split(" ")
        if words[0] == self.character_name:
            command = []
            command = [str(word) for word in words[1:] if word != ""]
            return command
        if words[0] == "Queue":
            self.queue_manager.create_queue(words[1])
            return None
        if words[0] == "Queue_Spot":
            queue = self.queue_manager.get_queue(words[1])
            queue.create_spot(
                int(words[2]),
                carb.Float3(float(words[3]), float(words[4]), float(words[5])),
                Utils.convert_angle_to_quatd(float(words[6])),
            )
            return None
        if words[0][0] == "#":
            return None

        return None

    # get simulation commands from both UI and command file
    def get_simulation_commands(self):
        """get simulation command from string files"""
        cmd_lines = self.get_combined_user_commands()
        commands = []
        for cmd_line in cmd_lines:
            command = self.convert_str_to_command(cmd_line)
            if command is not None:
                command_pair = (id, command)
                commands.append(command_pair)

        return commands

    # get character's position
    def get_current_position(self):
        return Utils.get_character_pos(self.character)

    # inject commands to character's command list
    def inject_command(
        self, command_list, executeImmediately=True, on_finished: Tuple[str, Callable[[str, str], None]] = None
    ):
        """
        Inject command to current commmand queue:

        inputs:
            command list: a list of command info that user what to inject
            execute Immediately: whether the commands would be execute immdiately or be conduct at the end of simulation
            on_finished_callback: tuple of callback info when injected commands finished execution
                                The first value in tuple is the callback id
                                The second value is the Callback to be invoked with (callcack_id, character_name)
        """
        cmd_array = self.handle_command_list(command_list)

        # Add inject command end checkpoint
        if on_finished:
            on_finished_id, on_finished_fn = on_finished
            self._command_callback_checkpoint[on_finished_id] = on_finished_fn
            cmd_array.append((on_finished_id, [COMMAND_CALLBCAK_CHECKPOINT]))

        # If commands need to be conducted immediately
        if executeImmediately:
            # inject the command at 1 or 0 index of the command array
            if self.commands and cmd_array:
                self.commands[1:1] = cmd_array
            else:
                self.commands[0:0] = cmd_array
        else:
            # append command list at the end of the command array
            self.commands.extend(cmd_array)

        carb.log_warn(f"After command injection, commands for {self.character_name} are: {self.commands}")

    # Replace all commands in character's command list
    def replace_command(self, command_list, on_finished: Tuple[str, Callable[[str, str], None]] = None):
        """
        Replace current command with input command list:

        Inputs:
            command list: a list of command
            on_finished_callback: tuple of callback info when injected commands finished execution
                                The first value in tuple is the callback id
                                The second value is the Callback to be invoked with (callcack_id, character_name)
        """
        cmd_array = self.handle_command_list(command_list)

        # Add inject command end checkpoint
        if on_finished:
            on_finished_id, on_finished_callback = on_finished
            # Trigger and remove all exsiting callbacks to notify other systems
            for callback_id, callback_fn in self._command_callback_checkpoint:
                callback_fn(callback_id, self.character_name)
            self._command_callback_checkpoint.clear()
            # Add new checkpoint
            self._command_callback_checkpoint[on_finished_id] = on_finished_callback
            cmd_array.append((on_finished_id, [COMMAND_CALLBCAK_CHECKPOINT]))

        # Replace new commands
        self.commands = cmd_array

        # Handle current command
        self.end_current_command()
        self.current_command = None

        carb.log_warn(f"After command replacement, commands for {self.character_name} are: {self.commands}")

    def handle_command_list(self, command_list):
        """Convert command list into id-command pair"""
        cmd_array = []
        for command in command_list:
            # a placeholder value to ensure the format
            id = None
            if Utils.check_command_type(command) == "string":
                command_str = command
            elif Utils.check_command_type(command) == "pair":
                id, command_str = command
            else:
                carb.log_warn(f"Error as warn message: {command} has a wrong type : {type(command)}")
                continue
            listed_cmd = self.convert_str_to_command(command_str)

            if listed_cmd is not None:
                command_pair = (id, listed_cmd)
                cmd_array.append(command_pair)

        return cmd_array

    def get_command(self, command_pair):
        """
        Returns an instance of a command object based on the command.

        :param list[str] command: list of strings describing the command.
        :return: instance of a command object.
        :rtype: python object
        """

        command_id, command = command_pair

        command_params = {
            "character": self.character,
            "command": command,
            "character_name": str(self.character_name),
            "navigation_manager": self.navigation_manager,
            "command_id": command_id,
            "update_metadata_callback_fn": self.set_metadata_callback,
            # "character_prim_path":self.prim_path,
        }
        # if the command is not valid, return None
        if len(command) < 1:
            return None

        # Special case: reach a callback checkpoint
        if command[0] == COMMAND_CALLBCAK_CHECKPOINT:
            if command_id in self._command_callback_checkpoint:
                callback_fn = self._command_callback_checkpoint.pop(command_id)
                callback_fn(command_id, self.character_name)
            return None

        if command[0] == "GoTo":
            return GoTo(**command_params)
        elif command[0] == "Idle":
            return Idle(**command_params)
        elif command[0] == "Queue":
            return QueueCmd(**command_params, queue_manager=self.queue_manager)
        elif command[0] == "Dequeue":
            return Dequeue(**command_params, queue_manager=self.queue_manager)
        elif command[0] == "LookAround":
            return LookAround(**command_params)
        elif command[0] == "Sit":
            return Sit(**command_params)
        elif command[0] == "GoToSection":
            return GoToSection(**command_params)
        elif command[0] == "GoToObject":
            return GoToObject(**command_params)
        elif command[0] in self.custom_command_names:
            custom_command_item = self.custom_command_manager.get_custom_command_by_name(command[0])
            if custom_command_item.template == CustomCommandTemplate.TIMING:
                return TimingTemplate(**command_params, command_name=custom_command_item.name)
            elif custom_command_item.template == CustomCommandTemplate.TIMING_TO_OBJECT:
                return TimingToObjectTemplate(**command_params, command_name=custom_command_item.name)
            elif custom_command_item.template == CustomCommandTemplate.GOTO_BLEND:
                return GoToBlendTemplate(**command_params, command_name=custom_command_item.name)
            return None
        else:
            module_str = ".commands.{}".format(command[0].lower(), package=None)
            try:
                custom_class = getattr(importlib.import_module(module_str, package=__package__), command[0])
                return custom_class(**command_params)
            except (ImportError, AttributeError):
                carb.log_error(f"Module or Class for the command {command_pair} do not exist. Check the command again.")
            return None

    def get_origin_command_string(self, command):
        line = self.character_name
        for str in command:
            if str != self.character_name:
                line = line + " " + str
        return line

    def execute_command(self, commands, delta_time):
        """
        Executes commands in commands list in sequence. Removes a command once completed.

        :param list[list] commands: list of commands.
        :param float delta_time: time elapsed since last execution.
        """
        while not self.current_command:
            if not commands:
                return
            next_cmd = self.get_command(commands[0])
            if next_cmd:
                self.current_command = next_cmd
                # submit event :: command has been started
                self.subscription_to_command_start(self.current_command)
            else:
                commands.pop(0)  # Skip the command that cannot be executed

        try:
            if self.current_command.execute(delta_time):

                if self.current_command.get_command_name() == "QueueCmd":
                    # check whether character has occupied a spot in the queue
                    self.in_queue = self.current_command.current_spot is not None

                if self.current_command.get_command_name() == "Dequeue":
                    # set character's status to "not in queue"
                    self.in_queue = False
                # submit event :: command has been completed
                self.subscription_to_command_end(current_command=self.current_command)

                commands.pop(0)
                self.current_command = None
        except:
            carb.log_error(
                "{}: invalid command. Abort this execution.".format(
                    self.get_origin_command_string(self.current_command.command)
                )
            )
            self.current_command.exit_command()
            self.subscription_to_command_end(current_command=self.current_command, status=TaskStatus.failed)
            commands.pop(0)
            self.current_command = None

    def on_update(self, current_time: float, delta_time: float):
        """
        Called on every update. Initializes character at start, publishes character positions and executes character commands.
        :param float current_time: current time in seconds.
        :param float delta_time: time elapsed since last update.
        """
        if self.character is None:
            if not self.init_character():
                return
            else:
                # Once character is initialized correctly, register the agent to the AgentManager
                self.register_to_agent_manager()

        if self.navigation_manager and self.avoidanceOn:
            self.navigation_manager.publish_character_positions(delta_time, 0.5)

        if self.commands:
            self.execute_command(self.commands, delta_time)
        elif self.number_of_loop > self.loop_commands_count and self.loop_commands:
            self.commands = self.loop_commands.copy()
            self.loop_commands_count += 1

    def check_interruptable(self):
        return self.interruptable

    def set_interruptable(self, target_value):
        self.interruptable = target_value

    # ============ Overwrite values ================

    @property
    def overwrite_command_file(self):
        return self._overwrite_command_file

    @overwrite_command_file.setter
    def overwrite_command_file(self, value):
        self._overwrite_command_file = value

    @property
    def overwrite_agent_name(self):
        return self._overwrite_agent_name

    @overwrite_agent_name.setter
    def overwrite_agent_name(self, value):
        self._overwrite_agent_name = value
=== /isaac-sim/extscache/omni.anim.people-0.7.9+107.3.3/omni/anim/people/scripts/custom_command/command_manager.py ===
import carb
from typing import List
from omni.anim.people.scripts.custom_command.defines import *
from omni.metropolis.utils.file_util import JSONFileUtil
from omni.metropolis.utils.carb_util import CarbSettingUtil
from pxr import Sdf, Usd, UsdGeom


class CustomCommandManager:

    CUSTOM_COMMAND_TRACKING_FILE = "/persistent/exts/omni.anim.people/custom_command_tracking_file_path"
    CUSTOM_COMMAND_CHANGED_EVENT = "omni.anim.people.CUSTOM_COMMAND_CHANGED"

    __instance = None

    @classmethod
    def get_instance(cls):
        # Instance is created during extension start up
        return cls.__instance

    def __init__(self, ext_path):
        if CustomCommandManager.__instance is not None:
            raise RuntimeError("Only one instance of CustomCommandManager is allowed")
        CustomCommandManager.__instance = self
        self._ext_path = ext_path
        self._default_json_path = f"{self._ext_path}/data/custom_command_tracking.json"
        self._tracking_file_path = ""  # Json file that stores all custom commands links.
        self._commands: List[CustomCommand] = []  # CustomCommand loaded.
        self._stage = None  # Ghost stage to load all anim usd.

    def startup(self):
        self._setup_stage()
        self.load_entry_tracking_file()

    def shutdown(self):
        self._stage = None
        CustomCommandManager.__instance = None

    def register_custom_command_changed_callback(self, on_event: callable):
        return carb.eventdispatcher.get_eventdispatcher().observe_event(
            event_name=CustomCommandManager.CUSTOM_COMMAND_CHANGED_EVENT, on_event=on_event,
            observer_name="omni/anim/people/ON_CUSTOM_COMMAND_CHANGED"
        )

    def get_tracking_file_path(self):
        return self._tracking_file_path

    def _setup_stage(self):
        self._stage = Usd.Stage.CreateInMemory()
        default_prim = UsdGeom.Xform.Define(self._stage, Sdf.Path("/World")).GetPrim()
        self._stage.SetDefaultPrim(default_prim)

    def _load_anim_to_stage(self, anim_path):
        prim_name = get_anim_prim_name(anim_path)
        prim = UsdGeom.Xform.Define(self._stage, Sdf.Path(f"/World/{prim_name}")).GetPrim()
        prim.GetPayloads().AddPayload(assetPath=anim_path)
        # Load basic attributes
        attr_name = prim.GetAttribute("CustomCommandName")
        attr_template = prim.GetAttribute("CustomCommandTemplate")
        attr_start_time = prim.GetAttribute("CustomCommandAnimStartTime")
        attr_end_time = prim.GetAttribute("CustomCommandAnimEndTime")
        attr_loop = prim.GetAttribute("CustomCommandAnimLoop")
        attr_backwards = prim.GetAttribute("CustomCommandAnimBackwards")
        # Temp error checking before USD schema
        if not (attr_name.IsValid() and attr_template.IsValid()):
            carb.log_error(
                f"Animation USD {anim_path} misses custom command attributes.\nRequired attributes: 'CustomCommandName', 'CustomCommandTemplate'"
            )
            return None
        name = attr_name.Get()
        template = attr_template.Get()
        start_time = attr_start_time.Get()
        end_time = attr_end_time.Get()
        loop = attr_loop.Get()
        backwards = attr_backwards.Get()
        if name is None:
            carb.log_error(f"Animation USD {anim_path} has empty attribute CustomCommandName.")
            return None
        if template is None:
            carb.log_error(f"Animation USD {anim_path} has empty attribute CustomCommandTemplate.")
            return None
        cmd = CustomCommand(
            anim_path=anim_path,
            name=name,
            template=CustomCommandTemplate(template),
        )
        if start_time is not None:
            cmd.start_time = start_time
        if end_time is not None:
            cmd.end_time = end_time
        if loop is not None:
            cmd.loop = loop
        if backwards is not None:
            cmd.backwards = backwards
        # Unique attributes for different templates
        if cmd.template == CustomCommandTemplate.GOTO_BLEND:
            attr_filter_joint = prim.GetAttribute("CustomCommandFilterJoint")
            if attr_filter_joint.IsValid():
                cmd.filter_joint = attr_filter_joint.Get()
        # Randomization attribute
        if cmd.template == CustomCommandTemplate.TIMING or cmd.template == CustomCommandTemplate.TIMING_TO_OBJECT:
            cmd.min_random_time = prim.GetAttribute("CustomCommandRandomMinTime").Get()
            cmd.max_random_time = prim.GetAttribute("CustomCommandRandomMaxTime").Get()
            if cmd.template == CustomCommandTemplate.TIMING_TO_OBJECT:
                cmd.interact_object_filter = prim.GetAttribute("CustomCommandInteractObjectFilter").Get()
        # Unload prim after info is extracted
        self._stage.RemovePrim(prim.GetPrimPath())
        return cmd

    def load_entry_tracking_file(self):
        file_path = CarbSettingUtil.get_value_by_key(
            key=CustomCommandManager.CUSTOM_COMMAND_TRACKING_FILE,
            fallback_value=self._default_json_path,
            override_setting=True,
        )
        self.load_tracking_file(file_path)

    def load_tracking_file(self, json_file_path):
        self._commands.clear()
        self._tracking_file_path = json_file_path
        CarbSettingUtil.set_value_by_key(
            key=CustomCommandManager.CUSTOM_COMMAND_TRACKING_FILE, new_value=self._tracking_file_path
        )
        json_data = JSONFileUtil.load_from_file(json_file_path)
        if not json_data:
            carb.log_error("Loading custom commands json fails.")
            return
        if "animations" not in json_data:
            carb.log_error(f"Unable to find 'animations' from {json_file_path}, loading custom commands fails.")
            return
        animations_data = json_data["animations"]
        for anim_path in animations_data:
            self.add_custom_command(anim_path)

    def save_tracking_file(self):
        if not self._tracking_file_path:
            carb.log_error("Custom commands json is not loaded. Saving custom commands fails.")
            return
        data = {}
        data["animations"] = []
        for cmd in self._commands:
            data["animations"].append(cmd.anim_path)
        if JSONFileUtil.write_to_file(self._tracking_file_path, data):
            carb.log_info("Custom Command Tracking File is saved.")

    def add_custom_command(self, anim_path):
        if self.is_custom_command_anim_exist(anim_path):
            carb.log_warn("Animation USD is already in the list.")
            return False
        item = self._load_anim_to_stage(anim_path)
        if self.is_custom_command_name_exist(item.name):
            carb.log_warn("Custom command '{item.name}' is already in the list.")
            return False
        self._commands.append(item)
        carb.eventdispatcher.get_eventdispatcher().dispatch_event(
            event_name=CustomCommandManager.CUSTOM_COMMAND_CHANGED_EVENT, payload={}
        )
        return True

    def remove_custom_command(self, anim_path):
        item_to_remove = None
        for item in self._commands:
            if item.anim_path == anim_path:
                item_to_remove = item
                break
        if item_to_remove:
            self._commands.remove(item_to_remove)
            carb.log_info("Command {} has been removed:".format(str(item_to_remove.name)))
            carb.eventdispatcher.get_eventdispatcher().dispatch_event(
                event_name=CustomCommandManager.CUSTOM_COMMAND_CHANGED_EVENT, payload={}
            )
            return True
        return False

    def is_custom_command_name_exist(self, name):
        for item in self._commands:
            if name == item.name:
                return True
        return False

    def is_custom_command_anim_exist(self, anim_path):
        for item in self._commands:
            if anim_path == item.anim_path:
                return True
        return False

    def get_all_custom_commands(self):
        return self._commands

    def get_custom_command_by_name(self, name):
        for item in self._commands:
            if name == item.name:
                return item
        return None

    def get_all_custom_command_names(self):
        names = []
        for item in self._commands:
            names.append(item.name)
        return names

    def get_latest_command(self):
        return self._commands[-1]

    def get_command_by_anim_path(self, anim_path):
        for item in self._commands:
            if item.anim_path == anim_path:
                return item

    def get_command_template_by_name(self, name):
        command = self.get_custom_command_by_name(name)
        if not command:
            return None
        return command.template
=== /isaac-sim/extscache/omni.anim.people-0.7.9+107.3.3/omni/anim/people/settings.py ===
PERSISTENT_SETTINGS_PREFIX = "/persistent"


class PeopleSettings:
    COMMAND_FILE_PATH = "/exts/omni.anim.people/command_settings/command_file_path"
    ROBOT_COMMAND_FILE_PATH = "/exts/omni.anim.people/command_settings/robot_command_file_path"
    NUMBER_OF_LOOP = "/exts/omni.anim.people/command_settings/number_of_loop"
    DYNAMIC_AVOIDANCE_ENABLED = "/exts/omni.anim.people/navigation_settings/dynamic_avoidance_enabled"
    NAVMESH_ENABLED = "/exts/omni.anim.people/navigation_settings/navmesh_enabled"
    CHARACTER_ASSETS_PATH = f"{PERSISTENT_SETTINGS_PREFIX}/exts/omni.anim.people/asset_settings/character_assets_path"
    BEHAVIOR_SCRIPT_PATH = (
        f"{PERSISTENT_SETTINGS_PREFIX}/exts/omni.anim.people/behavior_script_settings/behavior_script_path"
    )
    CHARACTER_PRIM_PATH = f"{PERSISTENT_SETTINGS_PREFIX}/exts/omni.anim.people/character_prim_path"
    CACHE_ACTION_METADATA = "/exts/omni.anim.people/cache_action_metadata"

    CHARACTER_FINAL_TARGET_DISTANCE = "/exts/omni.anim.people/final_target_distance"

class AgentEvent:
    AgentRegistered = "omni.anim.people/REGISTER_AGENT"
    CommandStartEvent = "omni.anim.people/CommandStartEvent"
    CommandEndEvent = "omni.anim.people/CommandEndEvent"
    MetadataUpdateEvent = "omni.anim.people/MetadataUpdateEvent"


class MetadataTag:
    AgentActionTag = "action_tag"


class CommandID:
    auto_prefix = "Auto"
    cutomized_command = "Cust"


class ConstantAddress:
    command_folder = "omni/anim/people/scripts"


class TaskStatus:
    interrupted = "interrupted"
    failed = "failed"
    default = "default"	
