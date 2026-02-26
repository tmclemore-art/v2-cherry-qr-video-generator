#!/bin/bash

# Cherry Video Generator - Quick Setup Script
# Run this after cloning the repository

echo "🍒 Cherry Video Generator - Setup"
echo "=================================="
echo ""

# Check Python
if command -v python3 &> /dev/null; then
    echo "✓ Python 3 found"
else
    echo "✗ Python 3 not found. Please install Python 3.8+"
    exit 1
fi

# Create directories
echo ""
echo "Creating directories..."
mkdir -p videos
mkdir -p generated_videos
chmod 755 generated_videos
echo "✓ Directories created"

# Install dependencies
echo ""
echo "Installing Python dependencies..."
pip3 install -r requirements.txt
echo "✓ Dependencies installed"

# Check for videos
echo ""
VIDEO_COUNT=$(find videos -name "*.mp4" 2>/dev/null | wc -l)
if [ "$VIDEO_COUNT" -eq 6 ]; then
    echo "✓ All 6 template videos found"
else
    echo "⚠ Only $VIDEO_COUNT template videos found (need 6)"
    echo "  Please add your template videos to the videos/ folder"
fi

echo ""
echo "=================================="
echo "✓ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Add your 6 template videos to videos/ folder"
echo "2. Run: python3 server.py"
echo "3. Open: http://localhost:5000"
echo ""
