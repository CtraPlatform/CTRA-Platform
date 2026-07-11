import pandas as pd
def time_to_minute(time_str):
    hours, minutes, seconds = map(int, time_str.split(':'))
    return (hours * 3600 + minutes * 60 + seconds)/60
def time_to_second(time_str):
    try:
        if not time_str or pd.isna(time_str):
            return 0
        parts = str(time_str).strip().split(':')
        if len(parts) != 3:
            return 0
        hours, minutes, seconds = map(int, parts)
        return hours * 3600 + minutes * 60 + seconds
    except Exception:
        return 0
def seconds_to_time(seconds):
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{int(hours):02d}:{int(minutes):02d}:{int(secs):02d}"
##分钟转为时间格式f"{int(hours):02d}:{int(minutes):02d}:{int(secs):02d}"
def minute_to_time(minutes):
    hours = minutes // 60
    mins = minutes % 60
    return f"{int(hours):02d}:{int(mins):02d}:00"