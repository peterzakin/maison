# Contributing to Maison

Thanks for your interest in contributing! This guide covers the basics to get you up and running.

## Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/peterzakin/maison.git
cd maison
```

### 2. Install

Maison requires Python 3.10 or later. Install the package in editable mode along with the test dependencies:

```bash
pip install -e .
pip install pytest pytest-asyncio
```

### 3. Run the tests

```bash
python -m pytest
```

All tests should pass before you open a pull request.

## Submitting changes

1. Create a branch for your change.
2. Make your change and ensure the tests pass.
3. Open a pull request against `main` with a clear description of what changed and why.
