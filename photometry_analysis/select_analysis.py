"""Choose input files and a destination on every run; no fixed data paths."""
from argparse import Namespace
from datetime import datetime
from pathlib import Path
import traceback
import webbrowser


def choose_and_run():
    import tkinter as tk
    from tkinter import filedialog, simpledialog, messagebox
    root = tk.Tk()
    root.withdraw()
    try:
        ppd = filedialog.askopenfilename(title='1. 분석할 PPD 파일 선택', filetypes=[('pyPhotometry', '*.ppd')])
        if not ppd:
            return 0
        events = filedialog.askopenfilename(title='2. 같은 세션의 events.csv 선택',
                                           initialdir=str(Path(ppd).parent), filetypes=[('CSV', '*.csv')])
        if not events:
            return 0
        destination = filedialog.askdirectory(title='3. 결과를 저장할 폴더 선택', initialdir=str(Path(ppd).parent))
        if not destination:
            return 0
        excluded = simpledialog.askstring('4. 이 파일에서 제외할 trial',
                                         '제외 번호를 입력하세요. 예: 3,7,12-15\n전체를 포함하려면 빈칸으로 두세요.',
                                         initialvalue='', parent=root)
        if excluded is None:
            return 0
        method_number = simpledialog.askinteger(
            '5. dF/F 계산 방법',
            '1: exponential 보정 + 세션 공통 F₀\n'
            '2: 필터링한 control 회귀값으로 나누기\n'
            '   100 × (signal_filt − 회귀값) / 회귀값',
            initialvalue=1, minvalue=1, maxvalue=2, parent=root)
        if method_number is None:
            return 0
        method = 'control_fit' if method_number == 2 else 'session_f0'
        from align_photometry import run
        out = Path(destination) / (Path(ppd).stem + '_aligned_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
        print(f'PPD: {ppd}\nEvents: {events}\nResults: {out}\nExcluded: {excluded or "none"}', flush=True)
        run(Namespace(ppd=ppd, events=events, out=str(out), digital=1, signal='analog_2',
                      control='analog_1', low_pass=20, exclude_trials=excluded, sync_pairs=None,
                      selection_json=None, method=method))
        webbrowser.open((out/'review.html').as_uri())
        messagebox.showinfo('분석 완료', f'결과가 저장되었습니다.\n{out}\n\n열린 HTML에서 trial을 추가로 제외하고 평균 CSV를 저장할 수 있습니다.')
        return 0
    except Exception as error:
        traceback.print_exc()
        messagebox.showerror('분석 실패', str(error))
        return 1
    finally:
        root.destroy()


if __name__ == '__main__':
    raise SystemExit(choose_and_run())
