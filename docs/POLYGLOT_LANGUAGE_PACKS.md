# Polyglot Language Packs

Sprout language packs localize registered language concepts without translating
user code or changing runtime semantics. Packs are declarative JSON resources:
they cannot execute code, and compilation never contacts a translation service.

## Selecting A Pack

Place the declaration at the first meaningful statement in a file:

```sprout
language "chinese-pack"

定义 打招呼(名字):
  输出 "你好，" + 名字
```

The declaration may follow a BOM, shebang, blank lines, or comments. A later
declaration is rejected. Selection precedence is:

1. `sprout run --language PACK`
2. the file declaration
3. `[language] default` in `sprout.toml`
4. `english-pack`

Imported files select their own packs, so one module can use English while
another uses Simplified Chinese. Exported names and all other user identifiers
remain exactly as written.

## Commands

```sh
sprout language list
sprout language validate chinese-pack
sprout language install ./my-pack.json
sprout language update my-pack
sprout language sync ./my-pack.json
```

`sync` adds missing catalog concepts using English fallback. It never marks
fallbacks as reviewed. Maintainers may opt into provisional generation with
`--translator-command`; the command receives JSON on standard input and returns
`{"translations": {"concept.id": "spelling"}}` on standard output. Generated
entries remain marked `generated` until a human reviews them.

## Safety And Compatibility

Pack validation rejects unknown concepts, duplicate or confusable spellings,
malformed diagnostic placeholders, unsupported schema/catalog versions, and
unsupported Sprout constraints. Registry packages must use type
`language-pack`, pass checksum verification, and contain one JSON pack with no
executable content.

English spellings remain accepted in every pack. Formatting preserves the
selected pack and normalizes recognized syntax aliases to the pack's preferred
spelling.
