

import asyncio
import inspect
import logging
import re

import suno.command
import suno.database
import suno.utils


class SuNoModule:

  name:str = "SuNoModule"
  command_prefix:str = name
  module_help:str = (
    "L'aide de ce module n'a pas été rédigée, n'hésitez pas"
    "à contacter Lainou#2122 ou tout autre personne du dev' pour la rédiger, "
    "ou pour vous l'expliquer."
  )
  command_info:dict = dict(
    help=dict()
  )

  test_command_info:dict = dict()

  def __hash__(self):
    return hash(f"SuNoModule-{self.name}")

  def __init__(self, app, logger_name=None):
    if logger_name is None:
      logger_name = self.name
    self.logger:logging.Logger = suno.utils.get_logger(
      logger_name,
      filename=f"logs/{logger_name}.log",
      noprint=True
    )
    self._app:discord.Client = app
    self.dev:bool = False
    self.command_info:dict = self.command_info.copy()
    self.command_info.setdefault("help", dict(help="Obtenir l'aide de ce module"))
    if self.config.TEST:
      self.command_info.update(self.test_command_info)
    self.check_integrity()

  def check_integrity(self):
    missing_method = ", ".join(
      f"_command_{command}"
      for command in self.command_info
      if not hasattr(self, f"_command_{command}")
    )
    if not missing_method:
      return
    self.early_failure()
    message = "\n".join((
      f"Integrity problems has been encountered in the {self.name} module.",
      f"Missing methods: {missing_method}. Please implement them."
    ))
    self.logger.error(message)
    raise ValueError(f"Some integrity checks failed.\n{message}")

  def early_failure(self):
    suno.utils.add_stdout_handler(self.logger)
    self.logger.setLevel(logging.DEBUG)
    self.logger.debug("Early failure: logger outputs on stdout.")

  @property
  def config(self):
    return self._app.config

  @property
  def loop(self):
    return self._app.loop

  def set_dev_mode(self, print_stdout=True):
    if not self.dev:
      self.dev = True
      if print_stdout:
        suno.utils.add_stdout_handler(self.logger)
      self.logger.setLevel(logging.DEBUG)
      self.logger.debug(f"Dev mode activated for module {self.name}.")

  async def on_ready(self, *args, **kwargs):
    self.logger.debug(f"Module {self.name} loaded and ready.")
    return False

  async def on_message(self, message, *args, **kwargs):
    self.logger_debug_function(f"Got message: {message.content}")
    return await self.handle_command(message)

  async def on_member_join(self, member, *args, **kwargs):
    self.logger_debug_function(f"New member just joined: {member.name}")
    return False

  async def on_reaction_add(self, reaction, user):
    return False

  async def on_reaction_remove(self, reaction, user):
    return False

  async def ban_member(self, member):
    suno.database.ban_member(member)
    await member.guild.ban(member)
    self.logger.debug(f"[discord] {member.mention} has been baned.")

  async def kick_member(self, member):
    suno.database.kick_member(member)
    await member.guild.kick(member)
    self.logger.debug(f"[discord] {member.mention} has been kicked.")

  async def send_to_system_channel(self, guild, to_send):
    if guild.system_channel is not None:
      self.logger.debug(f"[discord] Sending message \"{to_send}\" in {guild.system_channel.name}.")
      await guild.system_channel.send(to_send)
      return True
    else:
      self.logger.debug(f"There is no system channel. Cannot send message.")
    return False

  async def send_message(self, channel, to_send):
    self.logger.debug(f"[discord] Sending message \"{to_send}\" in {channel.name}.")
    await channel.send(to_send)
    return True

  def logger_debug_function(self, message):
    self.logger.debug(f"[{inspect.stack()[1][3]}] - {message}")

  async def handle_command(self, message):
    content = re.sub(r"\s{2,}", " ", message.content.strip())
    if content == "!help":
      await self._command_all_helps(message)
      return True
    if not content.startswith(f"!{self.command_prefix} "):
      return False
    module, command, *args = suno.command.split_args(content)
    args = list(args)
    if command not in self.command_info:
      return await self.send_message(
        message.channel,
        f"Commande inconnue: {command}"
      )
    self.logger_debug_function(f"Command matches {self.name}:{command}.")
    if args == ["help"]:
      return await self._specific_mommand_help(message, command)
    if not await self.check_command_syntax(message, command, tuple(args)):
      return await self.send_message(
        message.channel,
        f"Mauvaise syntaxe pour {self.command_prefix} {command}. \"!{self.command_prefix} {command} help\" pour"
        " afficher l'aide."
      )
    return await self.run_command_check_perm(message, command, tuple(args))

  async def check_command_syntax(self, message, command, args):
    cmd_info = self.command_info[command]
    parsed_params = list(self.extract_command_meta_info(args))
    if (getter := cmd_info.get("before_args")):
      before_args = getter(locals())
    else:
      before_args = tuple()
    for original_param, parameter in zip(args, parsed_params):
      if "args" not in cmd_info:
        continue
      matched = False
      for param_checker in cmd_info["args"]:
        if param_checker(*before_args, parameter):
          self.logger.debug(f"param \"{original_param}\" ({parameter}) matched!")
          matched = True
          break
      if not matched:
        self.logger.debug(f"param \"{original_param}\" ({parameter}) not matched!")
        return False
    for checker in cmd_info.get("all_args", tuple()):
      result = checker(*before_args, args, parsed_params)
      if not isinstance(result, bool):
        if isinstance(result, str):
          await self.send_message(message.channel, result)
        result = False
      if not result:
        self.logger.debug(f"params \"{args}\" ({parsed_params}) not matched!")
        return False
    return True

  def extract_command_meta_info(self, args):
    for arg in args:
      if re.match(r"<@[!&]?\d{18}>", arg):
        yield suno.command.args.mention
      yield suno.command.args.string

  async def run_command_check_perm(self, message, command, args):
    if not self.check_perms(message.author, command):
      return await self.send_message(
        message.channel,
        "Vous n'avez pas l'autorisation de lancer cette commande."
      )
    handler = getattr(self, f"_command_{command}")
    await handler(message, command, args)
    return True

  def get_role(self, *args, **kwargs):
    return self._app.get_role(*args, **kwargs)

  async def manage_role(self, action:str, *args, **kwargs):
    return await getattr(self._app, f"_sync_role_{action}")(*args, **kwargs)

  def check_perms(self, user, command):
    command_info = self.command_info[command]
    if not (roles := command_info.get("perms", {}).get("role")):
      return True
    roles = set([self.get_role(user.guild, role) for role in roles])
    return set(user.roles) & roles

    return True

  async def _command_help(self, message, command, args):
    await self.send_message(
      message.channel,
      self._build_module_md_help()
    )

  async def _command_all_helps(self, message):
    await self.send_message(
      message.channel,
      self._build_all_modules_md_help()
    )

  def _build_module_md_help(self):
    return "\n".join((
      f"```markdown",
      self._build_module_raw_help(),
      f"```",
    ))

  def _build_all_modules_md_help(self):
    return "\n".join((
      "```markdown",
      f"{self.config.LOAD_COMMAND}: load the server.",
      "\n".join(
        f"!{module.command_prefix} help"
        for module in self._app._modules
        if module.name != "ExampleModule"
      ),
      "```",
    ))

  def _build_module_raw_help(self):
    commands_help = "\n".join(
      f"{name}\n---\n{self.command_info[name].get('help', '')}\n"
      for name in self.command_info
    )
    commandes_with_perm = [
      f"{command} - {' - '.join(value.get('perms', {}).get('role', ('no perm', )))}"
      for command, value in self.command_info.items()
    ]
    return "\n".join((
      f"{self.name}",
      f"===",
      f"{self.module_help}",
      f"\nPréfix de commande: !{self.command_prefix}",
      "\nCommandes:\n * "+"\n * ".join(commandes_with_perm),
      f"",
      f"{commands_help}",
    ))

  async def _specific_mommand_help(self, message, command):
    return await self.send_message(
      message.channel,
      self.command_info[command].get("help", self.module_help)
    )