from pdf2image import convert_from_path
from PyPDF2 import PdfFileReader, PdfFileWriter
from tesserocr import PyTessBaseAPI
import pdftotext
import pandas as pd
import os
import re

class SectionExtraction:

  def __init__(self, path, page_range=[], need_OCR=False, remove_patterns=None, is_named=True):
    # Path of the PDF File
    self.path = path
    # Specified page numbers in page_range. Accounting for index starting at zero
    self.pages = [page_num-1 for page_num in list(range(page_range[0],page_range[1]+1))]
    # Whether the PDF is scanned and needs OCR 
    self.need_OCR = need_OCR
    # Regex patterns to remove from text i.e. common headers and footer
    self.remove_patterns = remove_patterns
    # Whether sections in the text are named
    self.is_named = is_named
    # PDF file subsetted by page_range. Used as input to OCR or PDF parser
    self.subset_pdf = None
    # Raw text returned from OCR or PDF parser. Will be transformed if preprocess() is called
    self.raw_text = None
    # Section titles include number and name e.g. 4.3.3 Auxillary Communication Payload
    self.titles = None

  def fileSubset(self):
    """Write temporary pdf file based on specified page range to read for OCR or pdfToText.
    """
    name = self.path.replace('.pdf','')
    pdf = PdfFileReader(self.path) 
    writer = PdfFileWriter()
    for page_num in self.pages:
      writer.addPage(pdf.getPage(page_num)) 

    self.subset_pdf = f'{name}_subset.pdf' #temporary file to contain subset of pdf with specified pages
    with open(self.subset_pdf,'wb') as f: 
      writer.write(f)

  def readPDF(self):
    """Run either OCR with specified pages or PDF parser on all pages depending on need_OCR. 
    """
    self.fileSubset()

    if self.need_OCR:
      imgs = convert_from_path(self.subset_pdf, 350, grayscale=True, use_pdftocairo=True) #convert pdf subset to images 
      self.raw_text = []

      #Get text with OCR
      with PyTessBaseAPI() as api:
        for img in imgs:
          api.SetImage(img)
          text = api.GetUTF8Text()
          self.raw_text.append(text) 

    else:
      #Get text with PDF parser
      with open(self.subset_pdf, 'rb') as f:
        self.raw_text = pdftotext.PDF(f)    

  def preprocess(self):
    """ Remove headers, footers, and other patterns from the raw text. Specify list of regex patterns in remove_patterns.
        Returns raw_text with all patterns removed. 
    """

    if self.remove_patterns is not None:
      combined_pattern = r''
      for pattern in self.remove_patterns:
        combined_pattern = combined_pattern + f'{pattern}|'
      self.raw_text = [re.sub(combined_pattern,'',string) for string in self.raw_text] #remove all specified regex patterns

    self.raw_text = [re.sub(r' {2,}',' ',string) for string in self.raw_text] #replace spaces 2 or bigger with a single space 

  def named_parent_mapping(self):
    """Return mapping of a parent section to a child section e.g. the name of 4.5 to the name of 4.5.1
    """
    number_pattern = r'(\d.)+'

    numbers = [re.match(number_pattern,title).group() for title in self.titles] #Get all numbers from section titles
    split_numbers = [re.findall('\d\.?',number) for number in numbers]
    split_parent_numbers = [[re.search(r'\d\.',number).group() for number in numbers if re.search(r'\d\.',number) is not None] for numbers in split_numbers]
    parent_numbers = [''.join(number).strip('.') for number in split_parent_numbers]
    parent_map = []

    for i in range(len(parent_numbers)):

      if re.match(r'\d\.',parent_numbers[i]) is None:
        parent_map.append(None)

      else:
        parent_pattern = f'(?<=^({parent_numbers[i]} )).*' #match for parent name according to parent number
        parent_name = set([re.search(parent_pattern,title).group() for title in self.titles if re.search(parent_pattern,title) is not None])
        parent_map.extend(parent_name)

    return parent_map


  def named_top_level_mapping(self):
    """Return mapping of the top level to a section e.g. the name of 4.5 to the name of 4.5.1.2
    """

    full_pattern = r'^(\d\.\d ).*'
    name_pattern = r'(?<=^(\d\.\d )).*'
    number_pattern = r'^(\d\.\d)'

    top_levels = [re.search(full_pattern,title).group() for title in self.titles if re.search(full_pattern,title) is not None] #get top level sections e.g. 4.3 SPACE SEGMENT
    top_level_names = [re.search(name_pattern,level).group() for level in top_levels] #get top level name e.g SPACE SEGMENT
    top_level_names = [name.strip() for name in top_level_names] #strip leading and trailing whitespaces
    top_level_numbers = [re.search(number_pattern,level).group() for level in top_levels] #get top level number e.g. 4.3

    top_level_map = []

    for i in range(len(top_level_numbers)):
      matching_sections = [title for title in self.titles if re.match(f'^({top_level_numbers[i]})',title) is not None]
      top_level_map.extend([top_level_names[i]]*len(matching_sections))
    
    return top_level_map

  def named_sections(self):

    title_match = r'\d\.[\d.]+.*' #match entire section title e.g. '4.3.3 Auxillary Communications Payload'
    number_match = r'\d\.[\d.]+'  #match section number only e.g. '4.3.3'
    name_match = r'(?<=[\. ])(\D)+' #match section name only e.g. 'Auxillary Communications Payload'

    joined_text = ''.join(self.raw_text) #join all pages into single string
    self.titles = re.findall(title_match,joined_text) #get full titles e.g. '4.3.3 Auxillary Communications Payload'
    
    section_numbers = [re.match(number_match,title).group() for title in self.titles] #get numbers e.g. '4.3.3'
    section_names = [re.search(name_match,title).group() for title in self.titles if re.search(name_match,title) is not None] #get names e.g. 'Auxillary Communications Payload'
    section_names = [name.strip() for name in section_names] #strip leading and trailing whitespace

    section_descriptions = re.split(title_match,joined_text) #split by section title
    section_descriptions = [description.replace('\n',' ') for description in section_descriptions] #replace line breaks with space
    section_descriptions = [description for description in section_descriptions if re.fullmatch(r' {2,}',description) is None] #remove multiple line breaks (2 or more spaces)
    section_descriptions = [description for description in section_descriptions if re.match(r'[ ]+\d+',description) is None] #handle main section titles e.g. '4 System and Interface Description' present when splitting by title match

    top_level_map = self.named_top_level_mapping()
    parent_map = self.named_parent_mapping()
    section_info = {'Number':section_numbers, 'Top Level':top_level_map, 'Parent':parent_map, 'Name':section_names,'Description':section_descriptions}
    
    return pd.DataFrame(section_info)
  
  def unnamed_sections(self):

    pass

  def extract(self):

    self.readPDF()
    self.preprocess()
    if self.is_named:
      output_df = self.named_sections()
      return output_df
    else:
      output_df = self.unnamed_sections()
      return output_df


