# slack_emoji_uploader

## Running tests

```bash
python setup.py test
```

## Building binary distribution

```bash
python setup.py bdist_wheel
```

## Running

### Preparation

slack_emoji_uploader relies on a Slack team to manage the emojis for that team

### Configuration

Before running, a configuration file should be created to indicate the Slack team that will be used for managing emojis. If you don't want to enter your email address, password, and/or two factor authentication codes to the application, you can provide a `slack.cookie` configuration value.
You will also want to add a profile for the images you want to upload. If you have a group of images that you want to assign the same id, you can use the pipe (|) character to separate them. The `<integer>.id` field will be the name of the emoji on slack.

Note: the `DEFAULT` section is considered the global scope, but values can be overridden inside other profiles.

```ini
[DEFAULT]
slack.team=kadeem
slack.cookie=<cookie value>

[profile]
1.id = alpha
1.filename = /tmp/alpha.png
2.id = bravo|beta
2.filename = bravo.png|/tmp/beta.png

[other_team]
slack.team=kazzer
1.id = kadeem
1.filename = kadeem.png
```

### Execution

```bash
slack_upload --start 1 --finish 2 --profile profile --upload-folder ~/Pictures --upload
```
