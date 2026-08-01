# Github fetch

A neofetch-like program for GitHub profiles. Shows user avatar as true-color ASCII art alongside profile information and top repositories.

## Features
- True-color ASCII avatar display
- Profile information (name, bio, location, stats)
- Top 5 repositories sorted by stars
- Cross-platform support (Windows, Linux, macOS)

## Requirements
- Python 3.7+
- requests
- pillow

## Installation

```bash
git clone https://github.com/alptekinnege/githubfetch.git
cd githubfetch
pip install -r requirements.txt
```

## Usage
```bash
python githubfetch.py <username>
```

Example:
```bash
python githubfetch.py torvalds
```

## Terminal Alias (optional)

Add an alias so you can run it from anywhere as `githubfetch <username>`:

**Bash** (`~/.bashrc`):
```bash
echo "alias githubfetch='python3 $(pwd)/githubfetch.py'" >> ~/.bashrc
source ~/.bashrc
```

**Zsh** (`~/.zshrc`):
```bash
echo "alias githubfetch='python3 $(pwd)/githubfetch.py'" >> ~/.zshrc
source ~/.zshrc
```

Then use it:
```bash
githubfetch torvalds
```

## Example Output
![example image](screenshot.png)

## License
This project is released into the public domain under the [Unlicense](LICENSE). See [unlicense.org](https://unlicense.org) for details.
