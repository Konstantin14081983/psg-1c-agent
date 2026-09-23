"""Versioned federal five-day calendar. Unsupported years fail closed."""
from datetime import date, timedelta

CALENDARS = {
    2025: {'off': ['01-01','01-02','01-03','01-04','01-05','01-06','01-07','01-08','02-23','03-08','05-01','05-02','05-08','05-09','06-12','06-13','11-03','11-04','12-31'], 'work':['11-01'], 'source':'ПП РФ 04.10.2024 №1335'},
    2026: {'off': ['01-01','01-02','01-03','01-04','01-05','01-06','01-07','01-08','01-09','02-23','03-08','03-09','05-01','05-09','05-11','06-12','11-04','12-31'], 'work':[], 'source':'ПП РФ 24.09.2025 №1466'},
    2027: {'off': ['01-01','01-02','01-03','01-04','01-05','01-06','01-07','01-08','02-22','02-23','03-08','05-01','05-03','05-09','05-10','06-12','06-14','11-04','11-05','12-31'], 'work':['02-20'], 'source':'ПП РФ 17.09.2026 №1187'},
}

class CalendarUnavailable(ValueError): pass

def is_working_day(day):
    if day.year not in CALENDARS:
        raise CalendarUnavailable(f'Производственный календарь РФ на {day.year} год не загружен — требуется уточнение')
    c=CALENDARS[day.year]; key=day.strftime('%m-%d')
    return key in c['work'] or (key not in c['off'] and day.weekday()<5)

def roll(day, direction=1):
    while not is_working_day(day):day+=timedelta(days=direction)
    return day

def span(day, count, direction=1):
    if count<1:raise ValueError('Число учебных дней должно быть положительным')
    day=roll(day,direction)
    for _ in range(count-1):day=roll(day+timedelta(days=direction),direction)
    return day
