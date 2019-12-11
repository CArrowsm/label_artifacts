from PyQt5.QtWidgets import (QApplication, QMainWindow, QLineEdit, QWidget,
                             QPushButton, QHBoxLayout, QVBoxLayout, QLabel,
                             QProgressBar)
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import pyqtSlot, pyqtSignal, Qt, QThread
from pyqtgraph import PlotWidget, plot
import pyqtgraph as pg
import sys  # We need sys so that we can pass argv to QApplication
import os
import io

import numpy as np
import paramiko
from getpass import getpass

from label import LabelImageApp

import time


class AuthenticateThread(QThread) :
    notifyProgress = pyqtSignal(list)

    def run(self) :
        pass

class DownloadThread(QThread):
    """A Thread dedicated to a progress bar widget to show
       image download progress."""
    def __init__(self, sftp, path_to_remote_img):
        self.path_to_remote_img = path_to_remote_img
        self.sftp = sftp
        super().__init__()
    # Send a pyqtSignal with :
    # list = [number of bits transferred, number of bits to transfer]
    notifyProgress = pyqtSignal(list)

    def run(self) :
        # Download the Image
        self.sftp.get(self.path_to_remote_img, "tmp.npy", callback=self.status_bar)

    def status_bar(self, packets_sent, packets_to_send) :
        l = [packets_sent, packets_to_send]

        # Notify the progress bar widget of download progress
        self.notifyProgress.emit(l)


class MainWindow(QWidget):

    def __init__(self, *args, **kwargs):
        super(MainWindow, self).__init__(*args, **kwargs)

        # Define the distance from top left of screen
        # (first two ints), x,y size of windows (last two ints)
        self.setGeometry(300, 400, 1000, 700)
        self.setStyleSheet(open('style.css').read())

        # Open remote connection to H4H
        # If this is successful, initUI will be called
        self.init_authentiation()



    def initUI(self) :
        """ The main Application UI """
        self.mode = "label"

        # --- WINDOW --- #
        self.setWindowTitle("Image Labelling")

        hbox = QHBoxLayout()
        vbox = QVBoxLayout()
        # --- ###### --- #

        # --- BUTTONS --- #
        s_button = QPushButton("Strong")
        w_button = QPushButton("Weak")
        n_button = QPushButton("None")
        s_button.setToolTip('Label this patient as having a strong artifact.')
        w_button.setToolTip('Label this patient as having a weak artifact.')
        n_button.setToolTip('Label this patient as having no artifacts.')
        s_button.setObjectName("label-slice")
        w_button.setObjectName("label-slice-center")
        n_button.setObjectName("label-slice")
        s_button.clicked.connect(lambda: self.on_click(result="s"))
        w_button.clicked.connect(lambda: self.on_click(result="w"))
        n_button.clicked.connect(lambda: self.on_click(result="n"))

        hbox.addStretch()
        hbox.addWidget(s_button)
        hbox.addWidget(w_button)
        hbox.addWidget(n_button)
        hbox.setSpacing(0)
        hbox.addStretch()
        # --- ###### --- #

        # --- Plot specific patient --- #
        self.plt_patient_box = QHBoxLayout()
        patient_input = QLineEdit()
        patient_input.setPlaceholderText("Type Specific Patient ID")
        patient_button = QPushButton("Plot Patient")
        patient_button.setObjectName("input")
        patient_button.clicked.connect(lambda:
                     self.plt_specific_patient(patient_input.text()))
        self.plt_patient_box.addWidget(patient_button)
        self.plt_patient_box.addWidget(patient_input)
        # self.plt_patient_box.setSpacing(4)
        # --- ################### --- #

        # ---  TEXT   --- #
        self.text_header = QLabel("")
        self.text_header.setAlignment(Qt.AlignCenter)
        vbox.addWidget(self.text_header)
        # --- ####### --- #


        # --- IMAGE --- #
        self.imageWidget = pg.ImageView()
        vbox.addWidget(self.imageWidget)
        # --- ----- --- #

        # Progress Bar #
        self.progressBar = QProgressBar(self)
        self.progressBar.setTextVisible(True)
        self.progressBar.setMinimum(0)
        self.progressBar.setMaximum(100)

        vbox.addLayout(hbox)
        vbox.addLayout(self.plt_patient_box)
        vbox.addWidget(self.progressBar)
        self.setLayout(vbox)

        # Initialize the data
        print("Initializing data")
        self.app_functions = LabelImageApp(saving=True,
                                           img_widget=self.imageWidget,
                                           sftp_client=self.sftp)
        self.current_patient = self.app_functions.index
        self.text_header.setText(f"Current Patient: {self.current_patient}")

        # Load the first patient in the GUI
        self.update_display()



    def plt_specific_patient(self, patient_id) :
        df = self.app_functions.label_df.copy()

        try :
            self.current_patient = df[df["patient_id"] == patient_id].index[0]
            # Valid patient. Update display
            self.update_display
        except ValueError :
            # Invalid patient. Do nothing.
            return
        self.update_display()



    def on_click(self, result=None) :
        slice_index = self.imageWidget.currentIndex
        # Processes the result and updates the label DF
        self.app_functions.process_result(result,
                                          index=self.current_patient,
                                          slice=slice_index)

        # Update current patient index
        self.current_patient = self.current_patient + 1

        # Plot the new patient in the GUI
        self.update_display()



    def init_authentiation(self) :
        """ The authentication window UI """
        # We are currently in "authentication mode"
        self.mode = "auth"

        # Set GUI title
        self.setWindowTitle("H4H Login")

        # Create a widget with username and password fields
        vbox = QVBoxLayout()
        user = QLineEdit()
        pw = QLineEdit()
        submit_button = QPushButton("Login")
        submit_button.setObjectName("login")
        submit_button.clicked.connect(lambda: self.authenticate(user.text(), pw.text(), vbox))
        pw.setEchoMode(QLineEdit.Password)
        user.setPlaceholderText("Username")
        pw.setPlaceholderText("Password")

        progress = QHBoxLayout()
        self.message = QLabel("Enter your H4H username and password")
        self.icon = QLabel("")
        progress.addWidget(self.message)
        progress.addWidget(self.icon)
        progress.addStretch()

        # Progress bar
        # self.progressBar = QProgressBar(self)
        # self.progressBar.setText("Loading Images")

        # Prompt user for their h4h cridentials
        vbox.addStretch()
        vbox.addLayout(progress)
        vbox.addWidget(user)
        vbox.addWidget(pw)
        vbox.addWidget(submit_button)
        # vbox.addWidget(self.progressBar)
        vbox.addStretch()
        self.setLayout(vbox)



    def authenticate(self, username, password, auth_widget) :

        try :
            self.sftp = self.setup_remote(username, password)
            print("Authentication Successful")
            # Remove the authentication widget
            QWidget().setLayout(auth_widget.layout())
            self.initUI()

        except :
            # Remove the authentication widget
            QWidget().setLayout(auth_widget.layout())
            print("Authentication Unsuccessful")

            # Ask for authentication again
            self.init_authentiation()



    def setup_remote(self, username, password) :
        host = "172.27.23.173"
        port = 22

        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.connect(host, port=port,
                       username=username, password=password)
        sftp_client = client.open_sftp()

        return sftp_client

    def get_img(self, path) :
        # Load the new image and send to the graphing GUI
        # self.sftp.get(path, "tmp.npy", callback=)
        self.load = DownloadThread(self.sftp, path)
        self.load.notifyProgress.connect(self.onProgress)
        self.load.start()

        # When finished downloading image, diplay it
        self.load.finished.connect(self.display_img)

    def display_img(self) :
        # Remove progress bar
        self.progressBar.setValue(0)
        self.progressBar.setFormat("")


        image = np.load("tmp.npy")

        os.remove("tmp.npy")

        image = image[:, 50:-175, 75:-75]

        # Convert the image to 16-bit integer
        image = image.astype(np.int16)
        # Normalize the image
        image = self.app_functions.normalize(image)

        self.imageWidget.setImage(image)

        # Update text header
        self.text_header.setText(f"Current patient: {self.current_patient}")


    def onProgress(self, l) :
        percent_done = (l[0] / (l[0] + l[1])) * 100

        self.progressBar.setFormat("Loading Images")

        self.progressBar.setValue(2*percent_done)


    def keyPressEvent(self, e):
        """ Handle key press events"""
        if e.key == 16777220 :
            # [Enter] key was hit
            if self.mode == "auth" :
                print("Authenticating")
            if self.mode == "label" :
                print("")

    def update_display(self) :
        patient_id = self.app_functions.label_df.loc[self.current_patient, "patient_id"]
        file_name = str(patient_id) + "_img.npy"
        img_path = os.path.join(self.app_functions.img_path, file_name)

        # Update Image widget
        print("Loading Image")
        self.get_img(img_path)
        print("Image transferred")



def main():
    app = QApplication(sys.argv)
    main = MainWindow()
    main.show()

    try :
        sys.exit(app.exec_())
    except :
        # Save progress
        main.app_functions.exit_app()

        # Close remote connections
        main.sftp.close()
        # main.t.close()

        # Close GUI
        app.quit()

        # Close python interpreter
        sys.exit()

if __name__ == '__main__':
    main()