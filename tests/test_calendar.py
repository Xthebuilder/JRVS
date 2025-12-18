"""
Unit tests for core.calendar module
Tests calendar event management functionality
"""
import pytest
import asyncio
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from core.calendar import Calendar
from core.database import Database


class TestCalendar:
    """Test suite for Calendar class"""
    
    @pytest.fixture
    async def temp_db(self):
        """Create a temporary database for testing"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.db', delete=False) as f:
            db_path = f.name
        
        test_db = Database(db_path)
        await test_db.initialize()
        
        yield test_db
        
        # Cleanup
        if os.path.exists(db_path):
            os.remove(db_path)
    
    @pytest.fixture
    async def calendar(self, temp_db, monkeypatch):
        """Create calendar with temporary database"""
        cal = Calendar()
        
        # Patch the global db instance to use temp_db
        from core import database
        monkeypatch.setattr(database, 'db', temp_db)
        
        await cal.initialize()
        
        yield cal
    
    @pytest.mark.asyncio
    async def test_initialization(self, calendar):
        """Test calendar initialization"""
        assert calendar.initialized is True
    
    @pytest.mark.asyncio
    async def test_add_event(self, calendar):
        """Test adding a calendar event"""
        title = "Test Meeting"
        event_date = datetime.now() + timedelta(days=1)
        description = "Test meeting description"
        
        event_id = await calendar.add_event(title, event_date, description)
        
        assert event_id is not None
        assert event_id > 0
    
    @pytest.mark.asyncio
    async def test_add_event_with_reminder(self, calendar):
        """Test adding event with reminder"""
        title = "Meeting with Reminder"
        event_date = datetime.now() + timedelta(hours=2)
        description = "Important meeting"
        reminder_minutes = 30
        
        event_id = await calendar.add_event(
            title, event_date, description, reminder_minutes
        )
        
        assert event_id > 0
    
    @pytest.mark.asyncio
    async def test_get_today_events_empty(self, calendar):
        """Test getting today's events when none exist"""
        events = await calendar.get_today_events()
        
        assert isinstance(events, list)
        assert len(events) == 0
    
    @pytest.mark.asyncio
    async def test_get_today_events_with_events(self, calendar):
        """Test getting today's events"""
        # Add an event for today
        title = "Today's Event"
        event_date = datetime.now().replace(hour=14, minute=30, second=0, microsecond=0)
        
        await calendar.add_event(title, event_date, "Test event for today")
        
        # Get today's events
        events = await calendar.get_today_events()
        
        assert len(events) >= 1
        assert any(event['title'] == title for event in events)
    
    @pytest.mark.asyncio
    async def test_get_upcoming_events(self, calendar):
        """Test getting upcoming events"""
        # Add events for different days
        today = datetime.now()
        
        await calendar.add_event("Event 1", today + timedelta(days=1), "Tomorrow")
        await calendar.add_event("Event 2", today + timedelta(days=3), "3 days")
        await calendar.add_event("Event 3", today + timedelta(days=10), "10 days")
        
        # Get upcoming events (default 7 days)
        events = await calendar.get_upcoming_events(days=7)
        
        assert len(events) >= 2  # First two events should be included
        assert any(event['title'] == "Event 1" for event in events)
        assert any(event['title'] == "Event 2" for event in events)
    
    @pytest.mark.asyncio
    async def test_get_upcoming_events_custom_days(self, calendar):
        """Test getting upcoming events with custom day range"""
        today = datetime.now()
        
        await calendar.add_event("Near Event", today + timedelta(days=2), "Soon")
        await calendar.add_event("Far Event", today + timedelta(days=20), "Later")
        
        # Get events for next 30 days
        events = await calendar.get_upcoming_events(days=30)
        
        assert len(events) >= 2
    
    @pytest.mark.asyncio
    async def test_get_month_events(self, calendar):
        """Test getting events for a specific month"""
        # Add event in specific month
        test_date = datetime(2025, 6, 15, 14, 0, 0)
        
        await calendar.add_event("June Event", test_date, "Event in June")
        
        # Get June events
        events = await calendar.get_month_events(2025, 6)
        
        assert len(events) >= 1
        assert any(event['title'] == "June Event" for event in events)
    
    @pytest.mark.asyncio
    async def test_delete_event(self, calendar):
        """Test deleting an event"""
        # Add an event
        event_id = await calendar.add_event(
            "Event to Delete",
            datetime.now() + timedelta(days=1),
            "This will be deleted"
        )
        
        # Delete the event
        result = await calendar.delete_event(event_id)
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_delete_nonexistent_event(self, calendar):
        """Test deleting a non-existent event"""
        result = await calendar.delete_event(99999)
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_update_event(self, calendar):
        """Test updating an event"""
        # Add an event
        event_id = await calendar.add_event(
            "Original Title",
            datetime.now() + timedelta(days=1),
            "Original description"
        )
        
        # Update the event
        new_title = "Updated Title"
        new_date = datetime.now() + timedelta(days=2)
        new_description = "Updated description"
        
        result = await calendar.update_event(
            event_id, new_title, new_date, new_description
        )
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_get_event_by_id(self, calendar):
        """Test retrieving a specific event by ID"""
        title = "Specific Event"
        event_date = datetime.now() + timedelta(days=1)
        
        event_id = await calendar.add_event(title, event_date, "Description")
        
        event = await calendar.get_event(event_id)
        
        assert event is not None
        assert event['title'] == title
        assert event['id'] == event_id
    
    @pytest.mark.asyncio
    async def test_get_nonexistent_event(self, calendar):
        """Test retrieving a non-existent event"""
        event = await calendar.get_event(99999)
        
        assert event is None
    
    @pytest.mark.asyncio
    async def test_check_reminders(self, calendar):
        """Test checking for upcoming reminders"""
        # Add event with reminder
        event_date = datetime.now() + timedelta(minutes=25)
        
        await calendar.add_event(
            "Reminder Event",
            event_date,
            "Event with reminder",
            reminder_minutes=30
        )
        
        # Check reminders
        reminders = await calendar.check_reminders()
        
        assert isinstance(reminders, list)
    
    @pytest.mark.asyncio
    async def test_multiple_initializations_idempotent(self, calendar):
        """Test that multiple initializations are safe"""
        await calendar.initialize()
        await calendar.initialize()
        
        assert calendar.initialized is True


class TestGlobalCalendarInstance:
    """Test the global calendar instance"""
    
    def test_global_instance_exists(self):
        """Test that global calendar instance exists"""
        from core.calendar import calendar
        
        assert calendar is not None
        assert isinstance(calendar, Calendar)
