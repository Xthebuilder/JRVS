#!/bin/bash
# Script to push JRVS with JARCORE to GitHub

cd /home/xmanz/JRVS

echo "Initializing git repository..."
git init

echo "Configuring git..."
git config user.email "your-email@example.com"
git config user.name "Xthebuilder"

echo "Staging all files..."
git add -A

echo "Creating commit..."
git commit -m "feat: Add JARCORE - JARVIS Autonomous Reasoning & Coding Engine

- AI-powered coding assistant using local Ollama models
- 11 new MCP tools for code generation, analysis, execution
- CLI interface with 7 commands (jarcore_cli.py)
- Interactive demo showcasing all features
- Support for 10+ programming languages
- Comprehensive documentation

Features:
- Code generation from natural language
- Comprehensive code analysis (bugs, security, performance)
- AI-powered refactoring
- Automatic test generation
- Safe code execution
- Intelligent error fixing
- File operations with auto-backup
- Code explanations in natural language

100% local, private, and free using Ollama models."

echo "Setting remote..."
git remote add origin https://github.com/Xthebuilder/JRVS.git || git remote set-url origin https://github.com/Xthebuilder/JRVS.git

echo "Setting up GitHub authentication..."
gh auth setup-git

echo "Pushing to GitHub (force to replace old JRVS)..."
git push -u origin main --force

echo "Done! JRVS with JARCORE pushed to GitHub."
