from app.db.db import Session, UserTaskAttempt


def get_attempt(user_id, task_id): #Получение кол-во попыток пользователя
     with Session() as session:
          attempt = session.query(UserTaskAttempt).filter_by(User_id = user_id, Task_id = task_id).first()
          if attempt:
               return {
                    'attempt_used': attempt.attempts_used,
                    'attempt_all': attempt.attempts_all
               }
          return {
            'attempt_used': 0,
            'attempt_all': 0
            }

def add_attempt(user_id, task_id): #Изменения кол-во используемых попыток пользователя
     with Session() as session:
               try:
                attempt = session.query(UserTaskAttempt).filter_by(User_id = user_id, Task_id = task_id).first()
                if attempt:
                        attempt.attempts_used += 1
                        attempt.attempts_all += 1
                else:
                    attempt = UserTaskAttempt(
                        User_id=user_id,
                        Task_id=task_id,
                        attempts_used=1,
                        attempts_all=1
                    )
                    session.add(attempt)
                session.commit()
               except Exception as e:
                    session.rollback()
                    print(f"Error updating attempt: {e}")
                    raise

def reset_attempt(user_id, task_id): 
        with Session() as session:
               try:
                attempt = session.query(UserTaskAttempt).filter_by(User_id = user_id, Task_id = task_id).first()
                if attempt:
                        attempt.attempts_used = 0
                        session.commit()
                        return True
               except Exception as e:
                    session.rollback()
                    print(f"Error reseting attempt: {e}")
                    raise