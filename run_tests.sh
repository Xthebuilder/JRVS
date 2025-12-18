#!/bin/bash
# Run tests and generate coverage report for JRVS

set -e

echo "=================================="
echo "JRVS Test Suite"
echo "=================================="

# Check if dependencies are installed
if ! python -m pytest --version > /dev/null 2>&1; then
    echo "Installing test dependencies..."
    pip install pytest pytest-asyncio pytest-cov coverage
fi

# Run tests with coverage
echo ""
echo "Running tests with coverage..."
python -m pytest tests/ -v --cov=. --cov-report=term-missing --cov-report=html --cov-report=xml -m "unit or integration"

# Display coverage summary
echo ""
echo "=================================="
echo "Coverage Summary"
echo "=================================="
python -m coverage report --skip-empty

# Check coverage threshold
COVERAGE=$(python -m coverage report --format=total 2>/dev/null || echo "0")
THRESHOLD=80

echo ""
echo "Total Coverage: ${COVERAGE}%"
echo "Target: ${THRESHOLD}%"

if (( $(echo "$COVERAGE < $THRESHOLD" | bc -l 2>/dev/null || echo "1") )); then
    echo "⚠️  Coverage is below ${THRESHOLD}%"
    echo "💡 Run 'open htmlcov/index.html' to see detailed coverage report"
else
    echo "✅ Coverage meets target of ${THRESHOLD}%"
fi

echo ""
echo "HTML coverage report: htmlcov/index.html"
echo "XML coverage report: coverage.xml"
