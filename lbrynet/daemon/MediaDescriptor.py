import subprocess
 
class Duration:
    def __init__(self, time):
        (self.hours, self.minutes, self.seconds) = time
    def all_in_millisec(self):
        return (int((float(self.hours) * 3600)  + (float(self.minutes) * 60) + (float(self.seconds))) * 1000); 
        

def get_video_length(path):
    process = subprocess.Popen(['/usr/bin/ffmpeg', '-i', path], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    stdout, stderr = process.communicate()

    for line in stdout.splitlines():
        if 'Duration' in line:
            line = line.replace(',', '')
            duration = Duration(line.split()[1].split(":"))
            return duration.all_in_millisec()

