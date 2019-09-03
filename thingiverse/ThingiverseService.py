# Copyright (c) 2018 Chris ter Beke.
# Thingiverse plugin is released under the terms of the LGPLv3 or higher.
import pathlib
import tempfile
from typing import List, Optional, Dict

from PyQt5.QtCore import QObject, pyqtProperty, pyqtSignal, pyqtSlot, QUrl
from PyQt5.QtWidgets import QMessageBox

from cura.CuraApplication import CuraApplication
from .ThingiverseApiClient import ThingiverseApiClient, JSONObject


class ThingiverseService(QObject):
    """
    The ThingiverseService uses the API client to serve Thingiverse content to the UI.
    """

    # Signal triggered when new things are found.
    thingsChanged = pyqtSignal()

    # Signal triggered when the active thing changed.
    activeThingChanged = pyqtSignal()

    # Signal triggered when the active thing files changed.
    activeThingFilesChanged = pyqtSignal()

    # Signal triggered when a file has started or stopped downloading.
    downloadingStateChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        # Hold the things found in search results.
        self._things = []  # type: List[JSONObject]
        self._search_page = 1  # type: int
        self._search_terms = ""  # type: str

        # Hold the thing and thing files that we currently see the details of.
        self._thing_details = None  # type: Optional[JSONObject]
        self._thing_files = []  # type: List[JSONObject]
        self._is_downloading = False  # type: bool

        # The API client that we do all calls to Thingiverse with.
        self._api_client = ThingiverseApiClient()  # type: ThingiverseApiClient

        # List of supported file types.
        self._supported_file_types = []  # type: List[str]

    def updateSupportedFileTypes(self) -> None:
        """
        Refresh the available file types (triggered when plugin window is loaded).
        """
        supported_file_types = CuraApplication.getInstance().getMeshFileHandler().getSupportedFileTypesRead()
        self._supported_file_types = list(supported_file_types.keys())

    @pyqtProperty("QVariantList", notify=thingsChanged)
    def things(self) -> List[Dict[str, any]]:
        """
        Get a list of found things. Updated when performing a search.
        :return: The things.
        """
        return [thing.__dict__ for thing in self._things]

    @pyqtProperty("QVariant", notify=activeThingChanged)
    def activeThing(self) -> Dict[str, any]:
        """
        Get the current active thing details.
        :return: The thing.
        """
        return self._thing_details.__dict__ if self._thing_details else None

    @pyqtProperty("QVariantList", notify=activeThingFilesChanged)
    def activeThingFiles(self) -> List[Dict[str, any]]:
        """
        Get the current active thing files.
        :return: The thing files.
        """
        return [files.__dict__ for files in self._thing_files]

    @pyqtProperty(bool, notify=activeThingChanged)
    def hasActiveThing(self) -> bool:
        """
        Whether there is currently a thing active to show or not.
        :return: True when there is an active thing, false otherwise.
        """
        return bool(self._thing_details)

    @pyqtProperty(bool, notify=downloadingStateChanged)
    def isDownloading(self) -> bool:
        """
        Whether there is currently a download in progress or not.
        :return: True if currently downloading, false otherwise.
        """
        return self._is_downloading

    @pyqtSlot(str, name="search")
    def search(self, search_terms: str) -> None:
        """
        Search for things by search terms.
        The search is done async and the result will be populated in self._things.
        :param search_terms: The search terms separated by a space.
        """
        self._clearSearchResults()
        self.hideThingDetails()
        self._search_page = 1
        self._search_terms = search_terms  # store search terms so we can append with pagination
        self._api_client.search(self._search_terms, self._onSearchFinished, on_failed=self._onRequestFailed,
                                page=self._search_page)

    @pyqtSlot(name="addSearchPage")
    def addSearchPage(self) -> None:
        """
        Append search Thing list with the next page of results.
        The search is done async and the result will be populated in self._things.
        """
        self._search_page += 1
        self._api_client.search(self._search_terms, self._onSearchFinished, on_failed=self._onRequestFailed,
                                page=self._search_page)

    @pyqtSlot(int, name="showThingDetails")
    def showThingDetails(self, thing_id: int) -> None:
        """
        Get and show the details of a single thing.
        :param thing_id: The ID of the thing.
        """
        self._api_client.getThing(thing_id, self._onThingDetailsFinished, on_failed=self._onRequestFailed)
        self._api_client.getThingFiles(thing_id, self._onThingFilesFinished, on_failed=self._onRequestFailed)

    @pyqtSlot(name="hideThingDetails")
    def hideThingDetails(self) -> None:
        """
        Remove the thing details. This hides the detail page in the UI.
        """
        self._thing_details = None
        self.activeThingChanged.emit()

    @pyqtSlot(int, str, name="downloadThingFile")
    def downloadThingFile(self, file_id: int, file_name: str) -> None:
        """
        Download and load a thing file by it's ID.
        The downloaded object will be placed on the build plate.
        :param file_id: The ID of the file.
        :param file_name: The name of the file.
        """
        self._is_downloading = True
        self.downloadingStateChanged.emit()
        self._api_client.downloadThingFile(file_id, lambda data: self._onDownloadFinished(data, file_name))

    def _onThingDetailsFinished(self, thing: JSONObject) -> None:
        """
        Callback for receiving thing details on.
        :param thing: The thing.
        """
        self._thing_details = thing
        self.activeThingChanged.emit()

    def _onThingFilesFinished(self, thing_files: List[JSONObject]) -> None:
        """
        Callback for receiving a list of thing files on. Filtered on supported file types of Cura.
        :param thing_files: The thing files.
        """
        self._thing_files = [f for f in thing_files if pathlib.Path(f.name).suffix.lower().strip(".")
                             in self._supported_file_types]
        self.activeThingFilesChanged.emit()

    def _onDownloadFinished(self, file_bytes: bytes, file_name: str) -> None:
        """
        Callback to receive the file on.
        :param file_bytes: The file as bytes.
        :param file_name: The file name.
        """
        file = tempfile.NamedTemporaryFile(suffix=file_name, delete=False)
        file.write(file_bytes)
        file.close()
        CuraApplication.getInstance().readLocalFile(QUrl().fromLocalFile(file.name))
        self._is_downloading = False
        self.downloadingStateChanged.emit()

    def _onSearchFinished(self, things: List[JSONObject]) -> None:
        """
        Callback for receiving search results on.
        :param things: The found things.
        """
        self._things.extend(things)
        self.thingsChanged.emit()

    def _clearSearchResults(self) -> None:
        """
        Clear all Thing search results.
        """
        self._things = []
        self.thingsChanged.emit()

    @staticmethod
    def _onRequestFailed(error: Optional[JSONObject] = None) -> None:
        """
        Callback for when a request failed.
        :param error: An optional error object that was returned by the Thingiverse API.
        """
        mb = QMessageBox()
        mb.setIcon(QMessageBox.Critical)
        mb.setWindowTitle("Oh no!")
        error_message = "Unknown"
        if error:
            error_message = error.error if hasattr(error, "error") else error
        mb.setText("Thingiverse returned an error: {}.".format(error_message))
        mb.setDetailedText(str(error.__dict__) if error else "")
        mb.exec()
