/**
 * Bot entrypoint. Wires config → client → voice → playback → commands,
 * registers the slash commands for the allowed guild, and dispatches
 * interactions to the handler.
 */

import {
  Client,
  Events,
  GatewayIntentBits,
  REST,
  Routes,
  type ChatInputCommandInteraction,
} from "discord.js";

import { generateDependencyReport } from "@discordjs/voice";

import { parseConfig } from "./config";
import { MusicDlClient } from "./musicDlClient";
import { QueueState } from "./queue";
import { VoiceManager, Playback } from "./player";
import { buildCommands, handleInteraction } from "./commands";

async function main(): Promise<void> {
  const config = parseConfig();

  console.log("=== voice dependency report ===");
  console.log(generateDependencyReport());
  console.log("================================");

  const client = new Client({
    intents: [
      GatewayIntentBits.Guilds,
      GatewayIntentBits.GuildVoiceStates,
      GatewayIntentBits.GuildMessages,
    ],
  });

  const musicDl = new MusicDlClient(config.musicDlBaseUrl, config.musicDlBotToken);
  const queue = new QueueState();
  const voice = new VoiceManager();
  const playback = new Playback(voice, queue, musicDl);

  const logger = {
    error: (...args: unknown[]) => console.error("[bot]", ...args),
  };
  const deps = { config, client: musicDl, queue, voice, playback, logger };

  // Register slash commands for the allowed guild only.
  const rest = new REST({ version: "10" }).setToken(config.discordToken);
  const commands = buildCommands().map((c) => c.toJSON());
  await rest.put(
    Routes.applicationGuildCommands(
      config.discordApplicationId,
      config.allowedGuildId,
    ),
    { body: commands },
  );
  console.log(`Registered ${commands.length} slash commands.`);

  client.on(Events.InteractionCreate, async (interaction) => {
    if (!interaction.isChatInputCommand()) return;
    await handleInteraction(
      interaction as ChatInputCommandInteraction,
      deps,
    );
  });

  client.once(Events.ClientReady, (c) => {
    console.log(`Logged in as ${c.user.tag}.`);
  });

  await client.login(config.discordToken);
}

main().catch((err) => {
  console.error("Fatal:", err);
  process.exit(1);
});
