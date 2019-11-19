"""
logger utility
"""
import datetime


error_log_filename = 'save/error.log'


def get_experiment_log_filepath():
    return 'save/experiment-log-%s.txt' % datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def log_progress(fpath, epoch, loss):
    buff = 'epoch:\t'+ str(epoch) + '\tnll:\t' + str(loss) + '\n'
    return write_log(fpath, buff)


def log_error(error_string):
	return write_log(error_log_filename,  error_string)


def write_log(fpath, buff):
    datestring = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    buff = datestring + '\t' + str(buff)
    print buff
    with open(fpath, 'a') as f:
        f.write(buff + '\n')
    return buff

