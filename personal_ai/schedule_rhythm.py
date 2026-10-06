"""Deterministic recovery days; no LLM, workout API or training-data writes."""
class RecoveryRhythm:
    """Choose recovery from actual course load, never from a weekday."""
    def __init__(self):
        self.load_minutes = 0
        self.study_days = 0
        self.consecutive = 0
        self.after_assessment = False
        self.last_kind = None

    def choose(self, available_minutes, assessment=False, before_assessment=False):
        if assessment:
            return None
        if self.after_assessment or self.load_minutes >= 120 or self.study_days >= 3:
            return dict(task_type='休息', title='恢復日：留白休息', minutes=0,
                        reason='以休息為主，不需打卡或補進度。若想活動，可自選散步／伸展約 10 分鐘；完全休息也可以。')
        if (before_assessment and self.study_days >= 2) or (
                self.last_kind != '輕量學習' and (self.consecutive >= 2 or self.load_minutes >= 90)):
            return dict(task_type='輕量學習', title='輕量回顧：讀一小段筆記', minutes=min(10, max(1, available_minutes)),
                        reason='依累積學習量或即將到來的驗收，安排短時間回顧，不增加新核心教材。')
        return None

    def record(self, minutes, task_type, question_count=0):
        if task_type in ('休息', '運動建議'):
            self.load_minutes = self.study_days = self.consecutive = 0
            self.after_assessment = False
        else:
            self.load_minutes += max(0, minutes)
            self.study_days += 1
            self.consecutive = 0 if task_type == '輕量學習' else self.consecutive + 1
            self.after_assessment = question_count > 0
        self.last_kind = task_type
