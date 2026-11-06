# NFC Card Battler

A C# / .NET 10 terminal roguelite. Tap an NTAG215 card to load a character,
fight NPC enemies, then tap again to save. The card is the character's only
save file.

The current design and build order are in [the game spec](docs/NFC%20Card%20Battler%20-%20Game%20Spec.pdf).
The Python code in `outdated/` is old reference material and is not used by
this application.

## Getting started

See [the beginner setup guide](docs/Getting%20Started.md) for installing the
SDK, understanding the four projects, and the commands used to create them.

With the .NET 10 SDK installed, run these commands from this folder:

```powershell
dotnet build
dotnet run --project src/NfcBattler.Terminal
dotnet test
```

## Projects

| Project | Purpose |
| --- | --- |
| `NfcBattler.Core` | Battle engine, AI, and rules, independent of hardware and UI. |
| `NfcBattler.Cards` | NFC communication and card save format; references Core. |
| `NfcBattler.Terminal` | Console entry point; references Core and Cards. |
| `NfcBattler.Tests` | xUnit tests; references Core and Cards. |

The terminal now offers **Read character**, **Create character**, **Clear**, and **Exit**. It uses PCSC 7.0.1
and Microsoft's Iot.Device.Bindings 4.2.0 from the spec. Plug in the ACR1552U,
choose an option, and follow the prompts with an NTAG215 card held on the reader.
Both character options first load the card. An existing character is printed;
a blank card offers creation with a name and class, followed by `CREATE`
confirmation. The saved character is read back to verify the write.

Creation requires an already formatted, writable NTAG215. Existing characters,
malformed saves, unsupported versions, and unrelated content are never replaced.
Clear old text/URL content first if you want to use that card for a character.
The terminal resolves class IDs and equipped/unlocked moves using
`data/classes.json` and `data/moves.json`, copied beside the app during builds.
Edit the source JSON files and rebuild to update names and move attack bonuses.

Characters use one 64-byte NDEF MIME payload as defined in
`docs/memory_layout.md`. Current health resets to saved maximum health on load.
There is no backup slot or checksum; structural validation and read-back checks
cannot recover an interrupted save or detect every possible data corruption.
Battles and the styled interface are still future work.

Clear asks you to type `CLEAR`, then erases all user pages (4-129), leaving an
empty NDEF message. It reads back the full user area to verify the erase.
Formatting, identity, lock, and configuration pages are preserved. Recognized
game saves are protected and reserved for the separate admin wipe tool.

GET_VERSION must return all eight bytes through the ACR1552U's pass-through
command. Unsupported firmware or truncated responses produce an error rather
than guessing the card type. The PCSC-only fallback mentioned in the spec is
not implemented yet. Real reader/card round trips still need hardware testing.
