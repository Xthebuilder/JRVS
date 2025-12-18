#!/usr/bin/env python3
"""
Unit tests for core.calendar module
"""
import pytest
import asyncio
import tempfile
import os
from datetime import datetime, timedelta

from core.calendar import Calendar


@pytest.fixture
async def temp_calendar():
    """Create a temporary calendar for testing"""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.db') as f:
        db_path = f.name
    
    cal = Calendar(db_path)
    await cal.initialize()
    
    yield cal
    
    # Cleanup
    try:
        os.unlink(db_path)
    except:
        pass


@pytest.mark.unit
@pytest.mark.asyncio
async def test_calendar_initialization(temp_calendar):
    """Test calendar initialization"""
    assert temp_calendar._setup_complete is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_add_event(temp_calendar):
    """Test adding an event to the calendar"""
    event_date = datetime.now()
    
    event_id = await temp_calendar.add_event(
        title="Test Event",
        event_date=event_date,
        description="Test description"
    )
    
    assert isinstance(event_id, int)
    assert event_id > 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_today_events(temp_calendar):
    """Test getting today's events"""
    # Add an event for today
    today = datetime.now()
    await temp_calendar.add_event(
        title="Today Event",
        event_date=today,
        description="Event for today"
    )
    
    events = await temp_calendar.get_today_events()
    
    assert isinstance(events, list)
    assert len(events) >= 1
    assert any(e['title'] == "Today Event" for e in events)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_upcoming_events(temp_calendar):
    """Test getting upcoming events"""
    # Add events for the next few days
    for i in range(3):
        event_date = datetime.now() + timedelta(days=i+1)
        await temp_calendar.add_event(
            title=f"Future Event {i}",
            event_date=event_date,
            description=f"Event {i} days from now"
        )
    
    events = await temp_calendar.get_upcoming_events(days=7)
    
    assert isinstance(events, list)
    assert len(events) >= 3


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_events_by_date_range(temp_calendar):
    """Test getting events by date range"""
    start_date = datetime.now()
    end_date = start_date + timedelta(days=5)
    
    # Add event within range
    await temp_calendar.add_event(
        title="Range Event",
        event_date=start_date + timedelta(days=2),
        description="Event within range"
    )
    
    events = await temp_calendar.get_events_by_date_range(start_date, end_date)
    
    assert isinstance(events, list)
    assert len(events) >= 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_event(temp_calendar):
    """Test deleting an event"""
    # Add an event
    event_id = await temp_calendar.add_event(
        title="Delete Me",
        event_date=datetime.now(),
        description="This event will be deleted"
    )
    
    # Delete the event
    result = await temp_calendar.delete_event(event_id)
    
    assert result is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_event(temp_calendar):
    """Test updating an event"""
    # Add an event
    event_id = await temp_calendar.add_event(
        title="Original Title",
        event_date=datetime.now(),
        description="Original description"
    )
    
    # Update the event
    new_date = datetime.now() + timedelta(days=1)
    result = await temp_calendar.update_event(
        event_id=event_id,
        title="Updated Title",
        event_date=new_date,
        description="Updated description"
    )
    
    assert result is True
