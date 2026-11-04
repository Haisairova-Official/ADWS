#include <libime/core/historybigram.h>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>
int main(int argc,char**argv) {
 try {
  libime::HistoryBigram history;
  if(argc>1){std::ifstream input(argv[1],std::ios::binary);history.load(input);std::cout<<"Existing history loads successfully\n";}
  history.add(std::vector<std::string>{""});
  std::cout<<"Empty word accepted\n";
 }catch(const std::exception& error){std::cout<<"Exception: "<<error.what()<<"\n";}
}
